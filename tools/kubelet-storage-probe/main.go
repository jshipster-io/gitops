package main

import (
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

func main() {
	baseline := flag.Bool("baseline", false, "Expect the pre-retirement 200 baseline, never a passing retirement check")
	clientID := flag.String("client-id", "", "Expected kubelet managed identity client ID")
	objectID := flag.String("object-id", "", "Expected kubelet managed identity principal ID")
	flag.Parse()
	if *clientID == "" || *objectID == "" {
		panic("explicit kubelet client-id and object-id required")
	}
	expected := 403
	if *baseline {
		expected = 200
	}
	client := &http.Client{Timeout: 20 * time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(r *http.Request, v []*http.Request) error { return http.ErrUseLastResponse }}
	query := url.Values{"api-version": {"2018-02-01"}, "resource": {"https://storage.azure.com/"}, "client_id": {*clientID}}
	req, _ := http.NewRequest("GET", "http://169.254.169.254/metadata/identity/oauth2/token?"+query.Encode(), nil)
	req.Header.Set("Metadata", "true")
	response, err := client.Do(req)
	if err != nil {
		panic("IMDS request unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		panic(fmt.Sprintf("IMDS HTTP %d", response.StatusCode))
	}
	var token struct {
		AccessToken string `json:"access_token"`
	}
	if json.NewDecoder(response.Body).Decode(&token) != nil {
		panic("token decode failed")
	}
	parts := strings.Split(token.AccessToken, ".")
	if len(parts) != 3 {
		panic("invalid token")
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		panic("invalid claims")
	}
	var claims map[string]interface{}
	json.Unmarshal(raw, &claims)
	if claims["oid"] != *objectID {
		panic("not the expected kubelet identity")
	}
	if expiry, ok := claims["exp"].(float64); !ok || int64(expiry) <= time.Now().Unix()+60 {
		panic("expired token cannot prove denial")
	}
	good := true
	for _, container := range []string{"hasadnaa-documents", "loki-logs", "pg-backups"} {
		req, _ = http.NewRequest("GET", "https://jshipsterprod410479.blob.core.windows.net/"+container+"?restype=container", nil)
		req.Header.Set("Authorization", "Bearer "+token.AccessToken)
		req.Header.Set("x-ms-version", "2023-11-03")
		r, e := client.Do(req)
		if e != nil {
			panic("storage request unavailable")
		}
		r.Body.Close()
		fmt.Printf("Kubelet %s metadata HTTP %d (expected %d)\n", container, r.StatusCode, expected)
		if r.StatusCode != expected {
			good = false
		}
		if expected == 403 && r.Header.Get("x-ms-error-code") != "AuthorizationPermissionMismatch" {
			fmt.Println("Unexpected storage rejection reason:", r.Header.Get("x-ms-error-code"))
			good = false
		}
	}
	if !good {
		os.Exit(1)
	}
}
