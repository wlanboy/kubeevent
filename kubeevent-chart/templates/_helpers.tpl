{{/* Standard-Labels für alle Ressourcen */}}
{{- define "kubeevent.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{/* Selector bleibt bei "app", Selektoren eines Deployments sind unveränderlich */}}
{{- define "kubeevent.selectorLabels" -}}
app: {{ .Values.deploymentName }}
{{- end }}
