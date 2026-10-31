// Evaluate rendered pod templates using the same rules as Kubernetes PSA.
package main

import (
	"encoding/json"
	"fmt"
	core "k8s.io/api/core/v1"
	"k8s.io/pod-security-admission/api"
	"k8s.io/pod-security-admission/policy"
	"os"
)

type Input struct {
	Level   string
	Version string
	Pod     core.Pod
}

func main() {
	var inputs []Input
	if err := json.NewDecoder(os.Stdin).Decode(&inputs); err != nil {
		panic(err)
	}
	evaluator, err := policy.NewEvaluator(policy.DefaultChecks(), nil)
	if err != nil {
		panic(err)
	}
	failed := false
	for _, in := range inputs {
		level, err := api.ParseLevel(in.Level)
		if err != nil {
			panic(err)
		}
		version, err := api.ParseVersion(in.Version)
		if err != nil {
			panic(err)
		}
		result := policy.AggregateCheckResults(evaluator.EvaluatePod(api.LevelVersion{Level: level, Version: version}, &in.Pod.ObjectMeta, &in.Pod.Spec))
		if !result.Allowed {
			fmt.Fprintf(os.Stderr, "%s/%s: %s\n", in.Pod.Namespace, in.Pod.Name, result.ForbiddenDetail())
			failed = true
		}
	}
	if failed {
		os.Exit(1)
	}
	fmt.Printf("PSA: %d templates passed official Kubernetes rules\n", len(inputs))
}
