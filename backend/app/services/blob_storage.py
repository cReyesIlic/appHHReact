from pathlib import Path

from azure.storage.blob import BlobServiceClient, ContentSettings

from app.core.config import settings


class BlobStorageService:
    def enabled(self) -> bool:
        return bool(settings.azure_connection_string and settings.container_name)

    def download(self, blob_name: str | None, destination: Path) -> bool:
        content = self.download_bytes(blob_name)
        if content is None:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as file:
            file.write(content)
        return True

    def download_bytes(self, blob_name: str | None) -> bytes | None:
        if not blob_name or not self.enabled():
            return None
        client = BlobServiceClient.from_connection_string(settings.azure_connection_string)
        blob = client.get_blob_client(container=settings.container_name, blob=blob_name)
        return blob.download_blob().readall()

    def upload_bytes(self, blob_name: str | None, content: bytes, content_type: str | None = None) -> bool:
        if not blob_name or not self.enabled():
            return False
        client = BlobServiceClient.from_connection_string(settings.azure_connection_string)
        blob = client.get_blob_client(container=settings.container_name, blob=blob_name)
        kwargs = {"overwrite": True}
        if content_type:
            kwargs["content_settings"] = ContentSettings(content_type=content_type)
        blob.upload_blob(content, **kwargs)
        return True
