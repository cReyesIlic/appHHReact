from pathlib import Path

from azure.storage.blob import BlobServiceClient

from app.core.config import settings


class BlobStorageService:
    def enabled(self) -> bool:
        return bool(settings.azure_connection_string and settings.container_name)

    def download(self, blob_name: str | None, destination: Path) -> bool:
        if not blob_name or not self.enabled():
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        client = BlobServiceClient.from_connection_string(settings.azure_connection_string)
        blob = client.get_blob_client(container=settings.container_name, blob=blob_name)
        with destination.open("wb") as file:
            file.write(blob.download_blob().readall())
        return True
