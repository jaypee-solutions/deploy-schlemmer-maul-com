# Deploy Schlemmer Maul

## Fetch Records from Cloudflare

```bash
curl https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq
```
