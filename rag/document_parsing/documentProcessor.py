import fitz
from docx import Document
from rapidocr import RapidOCR



class DocumentProcessor:
    def __init__(self):
            self.ocr = RapidOCR()


    def parse_pdf(self, file_path):
        pages_data = []
        pdf = fitz.open(file_path)

        for pages in range(len(pdf)):
            page = pdf[pages]
            text = page.get_text().strip()

            if text:

                pages_data.append({
                    "page": pages + 1,
                    "text": text,
                    "source":"pdf_text"
                })

            else:
                pix = page.get_pixmap()
                image_bytes = pix.tobytes("png")

                result = self.parse_ocr(image_bytes)

                pages_data.append({
                    "page": pages + 1,
                    "text": "\n".join(result),
                    "source": "ocr"
                })
    
        pdf.close()

        return pages_data


    

    def parse_docx(self, file_path):
        doc = Document(file_path)
        extracted_data = []

        for index, paragraph in enumerate(doc.paragraphs, start=1):
            text = paragraph.text.strip()
            if text:
                extracted_data.append({
                    "item_index": index,
                    "text": text
                })

        return extracted_data

    def parse_txt(self, file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            text = file.read()

        return [
            {
                "text": text
            }
        ]

    def parse_ocr(self, image):

        result = self.ocr(image)

        return result.txts


    def parse(self, file_path):

        file_path = str(file_path)
        extension = file_path.lower().split(".")[-1]

        if extension == "pdf":
            return self.parse_pdf(file_path)

        elif extension == "docx":
            return self.parse_docx(file_path)

        elif extension == "txt":
            return self.parse_txt(file_path)

        elif extension in {"png", "jpg", "jpeg"}:
            return self.parse_ocr(file_path)

        else:
            raise ValueError(f"Unsupported file type: {file_path}")

  
     









    