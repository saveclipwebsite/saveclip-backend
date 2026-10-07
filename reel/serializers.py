from rest_framework import serializers

class ReelDownloadSerializer(serializers.Serializer):
    url = serializers.URLField()
