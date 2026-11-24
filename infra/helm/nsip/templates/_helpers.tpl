{{- define "nsip.image" -}}{{ .root.Values.global.imageRegistry }}/{{ .name }}:{{ .root.Values.global.imageTag }}{{- end -}}

{{- define "nsip.labels" -}}
app.kubernetes.io/part-of: nsip
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "nsip.securityContext" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: { drop: ["ALL"] }
  seccompProfile: { type: RuntimeDefault }
{{- end -}}
