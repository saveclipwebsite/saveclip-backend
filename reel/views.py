import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from django.http import FileResponse, JsonResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ReelDownloadSerializer


INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9._+\-]+$")


def validate_instagram_url(url: str) -> bool:
    """Allow only public Instagram post/reel URLs; never accept arbitrary URLs."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.hostname not in INSTAGRAM_HOSTS:
        return False

    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 2 and parts[0].lower() in {"reel", "reels", "p"} and bool(parts[1])


def ytdlp_options(**overrides):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            )
        },
    }
    options.update(overrides)
    return options


def extract_public_reel_info(url: str):
    """Extract metadata without downloading the video."""
    with yt_dlp.YoutubeDL(ytdlp_options()) as ydl:
        return ydl.extract_info(url, download=False)


def available_mp4_formats(info):
    """Return only real, directly downloadable MP4 formats with video + audio."""
    formats = []
    seen = set()

    for fmt in info.get("formats") or []:
        format_id = str(fmt.get("format_id") or "")
        ext = str(fmt.get("ext") or "").lower()
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")

        if not format_id or format_id in seen:
            continue
        if ext != "mp4" or vcodec in (None, "none") or acodec in (None, "none"):
            continue
        if not FORMAT_ID_RE.fullmatch(format_id):
            continue

        height = fmt.get("height")
        width = fmt.get("width")
        filesize = fmt.get("filesize") or fmt.get("filesize_approx")

        if height:
            quality = f"{int(height)}p"
        elif width:
            quality = f"{int(width)}w"
        else:
            quality = "MP4"

        item = {
            "format_id": format_id,
            "quality": quality,
            "ext": "mp4",
        }
        if filesize:
            item["filesize_formatted"] = format_bytes(filesize)

        formats.append((int(height or 0), item))
        seen.add(format_id)

    formats.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in formats]


def format_bytes(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class ReelInfoAPI(APIView):
    """Return thumbnail, duration and the actual MP4 formats available."""

    def post(self, request, *args, **kwargs):
        serializer = ReelDownloadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Please enter a valid Instagram Reel URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        url = serializer.validated_data["url"].strip()
        if not validate_instagram_url(url):
            return Response(
                {"error": "Please enter a valid Instagram Reel URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            info = extract_public_reel_info(url)
            formats = available_mp4_formats(info)

            if not formats:
                return Response(
                    {"error": "No downloadable video was found for this Reel."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "success": True,
                    "thumbnail": info.get("thumbnail"),
                    "duration": info.get("duration"),
                    "formats": formats,
                },
                status=status.HTTP_200_OK,
            )
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc).lower()
            if any(word in message for word in ("private", "login", "not found", "unavailable", "does not exist")):
                error = "This Reel is private or unavailable."
            else:
                error = "Unable to fetch this Reel. Please try again."
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"error": "Something went wrong. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ReelDownloadAPI(APIView):
    """Download one of the actual MP4 formats returned by ReelInfoAPI."""

    def post(self, request, *args, **kwargs):
        serializer = ReelDownloadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Please enter a valid Instagram Reel URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        url = serializer.validated_data["url"].strip()
        format_id = str(request.data.get("format_id") or "").strip()

        if not validate_instagram_url(url):
            return Response(
                {"error": "Please enter a valid Instagram Reel URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not format_id or not FORMAT_ID_RE.fullmatch(format_id):
            return Response(
                {"error": "Please select a valid video quality."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="saveclip_"))
        try:
            # Re-extract metadata so the format ID cannot be forged to an arbitrary
            # extractor expression. Only formats actually available for this Reel
            # are accepted.
            info = extract_public_reel_info(url)
            allowed_ids = {item["format_id"] for item in available_mp4_formats(info)}
            if format_id not in allowed_ids:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return Response(
                    {"error": "The selected video quality is no longer available."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            output_template = str(temp_dir / "saveclip_reel.%(ext)s")
            options = ytdlp_options(
                format=format_id,
                outtmpl=output_template,
                paths={"home": str(temp_dir)},
                nopart=True,
            )

            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])

            files = list(temp_dir.glob("*.mp4"))
            if not files:
                raise RuntimeError("No MP4 file was produced.")

            video_path = files[0]
            response = FileResponse(
                open(video_path, "rb"),
                as_attachment=True,
                filename="saveclip_reel.mp4",
                content_type="video/mp4",
            )

            # Delete the temporary download after Django closes the response.
            response._resource_closers.append(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
            return response

        except yt_dlp.utils.DownloadError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return Response(
                {"error": "Unable to download this Reel right now. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return Response(
                {"error": "Something went wrong while preparing the MP4. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def health_check(request):
    return JsonResponse({"status": "ok", "service": "SaveClip Instagram Reel Downloader"})
