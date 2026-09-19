"""ftw-slo: SLO-as-Code generator by Fractal Techware.

Reads SLO specs (YAML) and generates Prometheus recording rules and
multi-window, multi-burn-rate alerts (Google SRE Workbook), plus
PrometheusRule CRDs and Grafana dashboards (Pro) and error budget
reports (Studio).
"""
VERSION = "1.0.0"
__version__ = VERSION
