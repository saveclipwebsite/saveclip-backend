# SaveClip Instagram Reel Downloader Backend

Django REST API for the SaveClip frontend. It handles **publicly accessible Instagram Reel URLs only** and returns real MP4 formats exposed by the extractor.

## API

### Health
`GET /reels/health/`

### Reel information
`POST /reels/api/info/`

```json
{"url":"https://www.instagram.com/reel/SHORTCODE/"}
```

Response shape:

```json
{
  "success": true,
  "thumbnail": "https://...",
  "duration": 22,
  "formats": [
    {
      "format_id": "1080p",
      "quality": "1080p",
      "ext": "mp4",
      "filesize_formatted": "14.2 MB"
    }
  ]
}
```

Only formats actually returned by the extractor are exposed; the API does not invent quality buttons.

### Download
`POST /reels/api/download/`

```json
{
  "url":"https://www.instagram.com/reel/SHORTCODE/",
  "format_id":"1080p"
}
```

The endpoint streams the selected MP4 as an attachment and deletes its temporary server-side copy after the response is closed.

## Environment variables

- `SECRET_KEY`
- `DEBUG` (`false` in production)
- `ALLOWED_HOSTS` (comma-separated)
- `CORS_ALLOWED_ORIGINS` (comma-separated)
- `CORS_ALLOW_ALL_ORIGINS` (normally `false`)
- `RATE_LIMIT` (default `30/min`)

## Important

This project does not bypass private accounts, login requirements, DRM, or other access restrictions. Instagram extraction can change over time, so a public Reel is not guaranteed to be downloadable at every moment.
