{{- define "apgar.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "apgar.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "apgar.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "apgar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels of one component. Call with (dict "root" $ "component" "api"). */}}
{{- define "apgar.selectorLabels" -}}
app.kubernetes.io/name: {{ include "apgar.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "apgar.componentLabels" -}}
{{ include "apgar.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "apgar.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "apgar.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "apgar.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "apgar.uiImage" -}}
{{- printf "%s:%s" .Values.uiImage.repository (default .Chart.AppVersion .Values.uiImage.tag) -}}
{{- end -}}

{{- define "apgar.secretName" -}}
{{- default (printf "%s-secrets" (include "apgar.fullname" .)) .Values.existingSecret -}}
{{- end -}}

{{- define "apgar.clickhouseUrl" -}}
{{- if .Values.clickhouse.enabled -}}
{{- printf "http://%s-clickhouse:8123" (include "apgar.fullname" .) -}}
{{- else -}}
{{- .Values.clickhouse.external.url -}}
{{- end -}}
{{- end -}}

{{/* Host of publicUrl without the port, for the ingress and route host names. */}}
{{- define "apgar.publicHost" -}}
{{- regexReplaceAll ":[0-9]+$" (urlParse .Values.publicUrl).host "" -}}
{{- end -}}

{{- define "apgar.trustedProxyHops" -}}
{{- if kindIs "invalid" .Values.api.trustedProxyHops -}}
{{- if or .Values.ingress.enabled .Values.httpRoute.enabled -}}2{{- else -}}1{{- end -}}
{{- else -}}
{{- .Values.api.trustedProxyHops -}}
{{- end -}}
{{- end -}}

{{/* Fails the render with a message that says how to fix the values. */}}
{{- define "apgar.validate" -}}
{{- if not (regexMatch "^https?://[^/]+" .Values.publicUrl) -}}
{{- fail "publicUrl is required: the address people and exporters use, for example --set publicUrl=https://apgar.example.com" -}}
{{- end -}}
{{- if not .Values.existingSecret -}}
{{- if lt (len .Values.secret.secretKey) 32 -}}
{{- fail "set existingSecret, or secret.secretKey of at least 32 characters (openssl rand -hex 32). The chart never generates it, because a key that changes makes stored connection secrets unreadable." -}}
{{- end -}}
{{- if lt (len .Values.secret.adminToken) 16 -}}
{{- fail "set existingSecret, or secret.adminToken of at least 16 characters (openssl rand -hex 24)." -}}
{{- end -}}
{{- if not .Values.secret.clickhousePassword -}}
{{- fail "set existingSecret, or secret.clickhousePassword (openssl rand -hex 16)." -}}
{{- end -}}
{{- end -}}
{{- if and (not .Values.clickhouse.enabled) (not .Values.clickhouse.external.url) -}}
{{- fail "clickhouse.enabled is false, so clickhouse.external.url is required, for example https://abc.clickhouse.cloud:8443" -}}
{{- end -}}
{{- if and (kindIs "invalid" .Values.api.trustedProxyHops) (or .Values.ingress.enabled .Values.httpRoute.enabled) (ne .Values.ui.service.type "ClusterIP") -}}
{{- fail "ui.service.type exposes the UI directly while ingress or httpRoute is enabled, so a client could forge the ingress hop in X-Forwarded-For. Use ui.service.type=ClusterIP, or set api.trustedProxyHops." -}}
{{- end -}}
{{- if and .Values.clickhouse.enabled (eq .Values.clickhouse.user "default") -}}
{{- fail "clickhouse.user cannot be default with the bundled ClickHouse, which keeps the default user for local access. Use another name, for example apgar." -}}
{{- end -}}
{{- if and .Values.httpRoute.enabled (not .Values.httpRoute.parentRefs) -}}
{{- fail "httpRoute.enabled needs httpRoute.parentRefs, the Gateway that serves the route" -}}
{{- end -}}
{{- end -}}

{{/* Restricted Pod Security settings shared by every container. */}}
{{- define "apgar.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* Call with (dict "root" $ "uid" 10001). */}}
{{- define "apgar.podSecurityContext" -}}
runAsNonRoot: true
{{- if .root.Values.fixedPodIds }}
runAsUser: {{ .uid }}
runAsGroup: {{ .uid }}
fsGroup: {{ .uid }}
{{- end }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Variables shared by the API, the worker, and migrate. */}}
{{- define "apgar.env" -}}
- name: APGAR_CLICKHOUSE_URL
  value: {{ include "apgar.clickhouseUrl" . | quote }}
- name: APGAR_CLICKHOUSE_USER
  value: {{ .Values.clickhouse.user | quote }}
- name: APGAR_CLICKHOUSE_DATABASE
  value: {{ .Values.clickhouse.database | quote }}
{{- if not .Values.clickhouse.enabled }}
- name: APGAR_CLICKHOUSE_VERIFY
  value: {{ .Values.clickhouse.external.verify | quote }}
{{- if .Values.clickhouse.external.caSecret }}
- name: APGAR_CLICKHOUSE_CA_CERT
  value: /etc/apgar/clickhouse-ca/ca.crt
{{- end }}
{{- end }}
- name: APGAR_CLICKHOUSE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "apgar.secretName" . }}
      key: APGAR_CLICKHOUSE_PASSWORD
- name: APGAR_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "apgar.secretName" . }}
      key: APGAR_SECRET_KEY
- name: APGAR_ADMIN_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "apgar.secretName" . }}
      key: APGAR_ADMIN_TOKEN
- name: APGAR_PUBLIC_URL
  value: {{ .Values.publicUrl | quote }}
- name: APGAR_TRUSTED_PROXY_HOPS
  value: {{ include "apgar.trustedProxyHops" . | quote }}
{{- range $name, $value := .Values.env }}
- name: {{ $name }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}

{{- define "apgar.envFrom" -}}
{{- with .Values.envFrom }}
envFrom:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* Mounts every Apgar container needs: a writable /tmp and the ClickHouse CA. */}}
{{- define "apgar.volumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- if and (not .Values.clickhouse.enabled) .Values.clickhouse.external.caSecret }}
- name: clickhouse-ca
  mountPath: /etc/apgar/clickhouse-ca
  readOnly: true
{{- end }}
{{- end -}}

{{- define "apgar.volumes" -}}
- name: tmp
  emptyDir: {}
{{- if and (not .Values.clickhouse.enabled) .Values.clickhouse.external.caSecret }}
- name: clickhouse-ca
  secret:
    secretName: {{ .Values.clickhouse.external.caSecret }}
{{- end }}
{{- end -}}

{{/* Restarts pods when the chart-managed Secret changes. */}}
{{- define "apgar.secretChecksum" -}}
{{- if not .Values.existingSecret -}}
checksum/secret: {{ include (print .Template.BasePath "/secret.yaml") . | sha256sum }}
{{- end -}}
{{- end -}}
