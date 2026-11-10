from pathlib import Path


class FileScanner:

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".docx",
        ".txt",
        ".png",
        ".jpg",
        ".jpeg"
    }

    def scan(self, folder_path):

        folder = Path(folder_path)
        files = []

        for file_path in folder.rglob("*"):

            if not file_path.is_file():
                continue

            if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                files.append(file_path)

        return files


