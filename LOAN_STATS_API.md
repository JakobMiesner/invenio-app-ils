# Loan Statistics API

The loan statistics endpoint provides librarians with powerful filtering and aggregation capabilities over loan data, returning histogram data over specified time intervals.

**Note**: This endpoint leverages the same filtering infrastructure as the regular loan listing endpoint (`/circulation/loans/`), ensuring consistency and reusing all existing facet configurations.

## Endpoint

```
GET /circulation/loans/stats
```

## Authorization

- Requires `stats-loans` permission
- Available to librarians with backoffice read-only access or higher

## Query Parameters

### Time Granularity
- `interval`: Time granularity for histogram (required)
  - `day` - Daily aggregation
  - `week` - Weekly aggregation
  - `month` - Monthly aggregation
  - `year` - Yearly aggregation

### Date Aggregation Field
- `field`: Date field to aggregate on (default: `start_date`)
  - `start_date` - When loan was initiated
  - `end_date` - When loan should be returned
  - `request_start_date` - When loan request was made
  - `request_expire_date` - When loan request expires

### Date Range Filters
- `from_date`: Start date filter (YYYY-MM-DD format)
- `to_date`: End date filter (YYYY-MM-DD format)

### Additional Filters
The endpoint supports all the same filters as the regular loan listing (`/circulation/loans/`):

- `state`: Loan state(s) to filter (can be multiple)
  - `PENDING`
  - `ITEM_ON_LOAN`
  - `ITEM_RETURNED`
  - `CANCELLED`
- `delivery`: Delivery method filter (can be multiple)
- `patron_pid`: Filter by specific patron PID
- `document_pid`: Filter by specific document PID
- `item_pid`: Filter by specific item PID
- `returns.end_date`: Filter overdue loans using special overdue logic
- Plus any other filters available in the loan facets configuration

## Example Requests

### Daily loan statistics for last 30 days
```bash
curl -H "Authorization: Bearer <token>" \
  "/circulation/loans/stats?interval=day&from_date=2024-01-01&to_date=2024-01-31"
```

### Weekly statistics for active loans only
```bash
curl -H "Authorization: Bearer <token>" \
  "/circulation/loans/stats?interval=week&state=ITEM_ON_LOAN&state=PENDING"
```

### Monthly statistics for specific patron
```bash
curl -H "Authorization: Bearer <token>" \
  "/circulation/loans/stats?interval=month&patron_pid=123&from_date=2024-01-01"
```

### Yearly overview with delivery method breakdown
```bash
curl -H "Authorization: Bearer <token>" \
  "/circulation/loans/stats?interval=year&delivery=pickup&delivery=mail"
```

## Response Format

```json
{
  "histogram": {
    "interval": "day",
    "field": "start_date",
    "buckets": [
      {
        "key": "2024-01-01",
        "doc_count": 15
      },
      {
        "key": "2024-01-02",
        "doc_count": 8
      }
    ]
  },
  "aggregations": {
    "by_state": [
      {
        "key": "ITEM_ON_LOAN",
        "doc_count": 45
      },
      {
        "key": "ITEM_RETURNED",
        "doc_count": 32
      }
    ],
    "by_delivery": [
      {
        "key": "pickup",
        "doc_count": 67
      },
      {
        "key": "mail",
        "doc_count": 10
      }
    ]
  },
  "total_loans": 77,
  "filters_applied": {
    "request_args": {
      "interval": "day",
      "from_date": "2024-01-01",
      "to_date": "2024-01-31",
      "state": ["ITEM_ON_LOAN", "ITEM_RETURNED"]
    },
    "facets_used": ["loans_from_date", "loans_to_date", "state"]
  }
}
```

## Response Fields

- `histogram`: Time-series data with specified granularity
  - `interval`: The requested time interval
  - `field`: The date field used for aggregation
  - `buckets`: Array of time buckets with document counts
- `aggregations`: Additional breakdowns of the data
  - `by_state`: Loan counts grouped by state
  - `by_delivery`: Loan counts grouped by delivery method
- `total_loans`: Total number of loans matching the filters
- `filters_applied`: Summary of filters applied to the query

## Use Cases

1. **Dashboard Analytics**: Create time-series charts showing loan activity
2. **Usage Patterns**: Identify peak borrowing times and trends
3. **Delivery Analysis**: Compare pickup vs delivery method usage
4. **Patron Activity**: Analyze individual patron borrowing patterns
5. **Collection Usage**: Track document popularity over time
6. **Operational Insights**: Monitor loan states and return patterns

## Error Responses

- `400 Bad Request`: Invalid parameters (e.g., wrong date format, invalid interval)
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: Insufficient permissions
- `500 Internal Server Error`: Server-side processing error
