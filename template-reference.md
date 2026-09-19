# SLI template reference

ftw-slo 1.0.0, Free edition: 3 templates. Generated with `ftw-slo templates --markdown`.

| Template | Kind | Category | Summary |
|---|---|---|---|
| [`generic-ratio`](#generic-ratio) | ratio | availability | Any event-based SLI from your own "bad events" and "all events" PromQL expressions. |
| [`http-availability`](#http-availability) | ratio | availability | Share of HTTP requests that did not fail with a server error (5xx). |
| [`http-latency`](#http-latency) | ratio | latency | Share of HTTP requests served faster than a threshold, from a classic histogram. |

## generic-ratio

**Generic ratio (two PromQL expressions)** (ratio, availability). Any event-based SLI from your own "bad events" and "all events" PromQL expressions.

Bring your own queries: errors_query returns bad events per second and total_query all
events per second, both using ${window} as the range. ftw-slo fills in 5m, 30m, 1h, ...
for every burn-rate window. When errors_query returns nothing (no bad events recorded
yet) the error ratio is 0, not "no data".

Requires: Two PromQL expressions returning per-second event rates.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `errors_query` | promql | **required** | Bad events per second; must contain ${window}. Example: `sum(rate(payments_failed_total[${window}]))` |
| `total_query` | promql | **required** | All events per second; must contain ${window}. Example: `sum(rate(payments_total[${window}]))` |

Query shapes (`${window}` is filled for every burn-rate window):

```promql
# errors
${errors_query}
# total
${total_query}
```

## http-availability

**HTTP availability** (ratio, availability). Share of HTTP requests that did not fail with a server error (5xx).

Availability of an HTTP service from a request counter with a status code label,
such as the Prometheus client libraries' http_requests_total{code}. 4xx responses
are client errors and count as good by default; tighten error_matcher to include
429 if throttling should burn budget.

Requires: A counter of HTTP requests with a status code label (default http_requests_total{code}).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `selector` | matchers | **required** | Label matchers selecting the service's requests. Example: `job="checkout"` |
| `metric` | metric | `http_requests_total` | Request counter name. |
| `error_matcher` | matchers | `code=~"5.."` | Matcher selecting failed requests. Use status=~"5.." or code=~"5..&#124;429" to fit your labels. |

Query shapes (`${window}` is filled for every burn-rate window):

```promql
# errors
sum${by}(rate(${metric}{${selector+error_matcher}}[${window}]))
# total
sum${by}(rate(${metric}{${selector}}[${window}]))
```

## http-latency

**HTTP latency (threshold)** (ratio, latency). Share of HTTP requests served faster than a threshold, from a classic histogram.

Latency SLI "99% of requests complete in under 300 ms". Uses the classic histogram
bucket at the threshold: slow requests = _count - _bucket{le="<threshold>"}. The
threshold must be an existing bucket boundary of your histogram. Prometheus 3
normalizes `le` labels to float notation (1 -> "1.0"); ftw-slo renders the
threshold the same way.

Requires: A classic histogram of request durations with a bucket at the threshold (default http_request_duration_seconds).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `selector` | matchers | **required** | Label matchers selecting the service's requests. Example: `job="checkout"` |
| `metric` | metric | `http_request_duration_seconds` | Histogram base name (without _bucket / _count). |
| `threshold` | le | `0.3` | Latency threshold in the histogram's unit; must equal a bucket `le` boundary. |
| `request_matcher` | matchers | (empty) | Optional extra matcher, e.g. code!~"5.." to judge only successful requests. |

Query shapes (`${window}` is filled for every burn-rate window):

```promql
# errors
sum${by}(rate(${metric}_count{${selector+request_matcher}}[${window}])) - sum${by}(rate(${metric}_bucket{${selector+request_matcher}, le="${threshold}"}[${window}]))
# total
sum${by}(rate(${metric}_count{${selector+request_matcher}}[${window}]))
```
