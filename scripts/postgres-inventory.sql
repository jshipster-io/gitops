-- Read-only, deterministic migration evidence. Run with psql -X -At and
-- ON_ERROR_STOP=1 against each database while application writers are stopped.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL extra_float_digits = 3;
SET LOCAL timezone = 'UTC';
SELECT json_build_object('kind','database','name',current_database(),
  'encoding',pg_encoding_to_char(encoding),'collate',datcollate,'ctype',datctype,
  'owner',pg_get_userbyid(datdba),'acl',datacl::text,'connection_limit',datconnlimit,
  'template',datistemplate,'allow_connections',datallowconn)
FROM pg_database WHERE datname=current_database();
SELECT json_build_object('kind','extension','name',extname,'version',extversion)
FROM pg_extension ORDER BY extname;
SELECT json_build_object('kind','relation','schema',n.nspname,'name',c.relname,
  'type',c.relkind,'owner',pg_get_userbyid(c.relowner),'acl',c.relacl::text,
  'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
AND n.nspname NOT LIKE 'pg_toast%' ORDER BY n.nspname,c.relname;
SELECT json_build_object('kind','column','schema',n.nspname,'table',c.relname,
  'name',a.attname,'type',format_type(a.atttypid,a.atttypmod),'notnull',a.attnotnull,
  'default',pg_get_expr(d.adbin,d.adrelid),'identity',a.attidentity,'generated',a.attgenerated)
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v','m','f')
AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname,c.relname,a.attnum;
SELECT json_build_object('kind','index','schema',n.nspname,'name',c.relname,
  'valid',i.indisvalid,'ready',i.indisready,'definition',pg_get_indexdef(i.indexrelid))
FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname,c.relname;
SELECT json_build_object('kind','constraint','schema',n.nspname,'table',c.relname,
  'name',co.conname,'validated',co.convalidated,'definition',pg_get_constraintdef(co.oid))
FROM pg_constraint co JOIN pg_class c ON c.oid=co.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
AND co.contype <> 'n' -- PostgreSQL 18 represents NOT NULL in pg_constraint.
ORDER BY n.nspname,c.relname,co.conname;
SELECT json_build_object('kind','default_acl','role',pg_get_userbyid(defaclrole),
  'schema',n.nspname,'type',defaclobjtype,'acl',defaclacl::text)
FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
ORDER BY pg_get_userbyid(defaclrole),n.nspname,defaclobjtype;
SELECT json_build_object('kind','function','schema',n.nspname,'name',p.proname,
  'arguments',pg_get_function_identity_arguments(p.oid),
  'owner',pg_get_userbyid(p.proowner),'acl',p.proacl::text,'definition',pg_get_functiondef(p.oid))
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND p.prokind IN ('f','p','w')
AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')
ORDER BY n.nspname,p.proname,pg_get_function_identity_arguments(p.oid);
SELECT json_build_object('kind','builtin_function_acl','function',p.oid::regprocedure::text,'acl',p.proacl::text)
FROM pg_proc p WHERE p.pronamespace='pg_catalog'::regnamespace AND p.proacl IS NOT NULL
AND EXISTS (SELECT 1 FROM aclexplode(p.proacl) a JOIN pg_roles r ON r.oid=a.grantee
            WHERE r.rolname NOT LIKE 'pg_%' AND r.rolname<>'postgres')
ORDER BY p.oid::regprocedure::text;
SELECT json_build_object('kind','trigger','schema',n.nspname,'table',c.relname,
  'name',t.tgname,'enabled',t.tgenabled,'definition',pg_get_triggerdef(t.oid))
FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE NOT t.tgisinternal ORDER BY n.nspname,c.relname,t.tgname;
SELECT json_build_object('kind','policy','schema',schemaname,'table',tablename,
  'name',policyname,'permissive',permissive,'roles',roles,'command',cmd,'using',qual,'check',with_check)
FROM pg_policies ORDER BY schemaname,tablename,policyname;
SELECT format('SELECT json_build_object(''kind'',''table_data'',''schema'',%L,''table'',%L,''count'',count(*),''fingerprint'',md5(coalesce(string_agg(h,'''' ORDER BY h COLLATE "C"),''''))) FROM (SELECT md5(to_jsonb(t)::text) h FROM ONLY %I.%I t) rows;',n.nspname,c.relname,n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN ('r','m') AND n.nspname NOT IN ('pg_catalog','information_schema')
AND n.nspname NOT LIKE 'pg_toast%' ORDER BY n.nspname,c.relname
\gexec
SELECT format('SELECT json_build_object(''kind'',''sequence'',''schema'',%L,''name'',%L,''last_value'',last_value,''is_called'',is_called) FROM %I.%I;',n.nspname,c.relname,n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='S' ORDER BY n.nspname,c.relname
\gexec
SELECT json_build_object('kind','large_object','oid',oid,'owner',pg_get_userbyid(lomowner),'acl',lomacl::text)
FROM pg_largeobject_metadata ORDER BY oid;
SELECT json_build_object('kind','large_object_data','oid',loid,'page',pageno,'hash',md5(data))
FROM pg_largeobject ORDER BY loid,pageno;
COMMIT;
