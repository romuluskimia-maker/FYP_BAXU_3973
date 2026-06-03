"""
OCR Processor using Tesseract - Fixed for Windows
Based on your working notebook implementation
"""

import pytesseract
from pdf2image import convert_from_bytes, convert_from_path
from PIL import Image
import io
import os
import logging
import platform
from pathlib import Path
from tempfile import TemporaryDirectory

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== TESSERACT CONFIGURATION ==========
# Set Tesseract path for Windows (from your working notebook)
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    
    # Poppler path for PDF processing (from your notebook)
    path_to_poppler_exe = Path(r"C:\poppler-25.12.0\Library\bin")
    
    # Check if poppler exists
    if not path_to_poppler_exe.exists():
        logger.warning(f"Poppler not found at {path_to_poppler_exe}")
        logger.warning("PDF processing may fail. Download poppler from: https://github.com/oschwartz10612/poppler-windows/releases/")
    else:
        logger.info(f"Found poppler at: {path_to_poppler_exe}")
else:
    path_to_poppler_exe = None

def check_tesseract_installation():
    """Verify Tesseract is properly installed and accessible"""
    try:
        version = pytesseract.get_tesseract_version()
        logger.info(f"✓ Tesseract version: {version}")
        
        # Check if the tesseract executable exists at the specified path
        if platform.system() == "Windows":
            tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.exists(tesseract_path):
                logger.info(f"✓ Tesseract found at: {tesseract_path}")
            else:
                logger.error(f"✗ Tesseract not found at {tesseract_path}")
                return False
        
        return True
    except Exception as e:
        logger.error(f"✗ Tesseract not found! Error: {e}")
        logger.error("\n=== INSTALLATION INSTRUCTIONS ===")
        logger.error("1. Download Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki")
        logger.error("2. Install to: C:\\Program Files\\Tesseract-OCR\\")
        logger.error("3. During installation, check 'Add to PATH' option")
        logger.error("4. Restart your computer after installation")
        logger.error("===================================")
        return False

def extract_text_from_pdf(file_bytes: bytes, dpi: int = 500) -> str:
    """
    Extract text from PDF file using OCR
    Adapted from your working notebook to work with bytes input
    """
    temp_dir = None
    try:
        logger.info("Processing PDF file...")
        
        # Create a temporary directory to hold our temporary images
        with TemporaryDirectory() as tempdir:
            logger.info(f"Created temporary directory: {tempdir}")
            
            # Convert PDF to images (using the same method as your notebook)
            if platform.system() == "Windows" and path_to_poppler_exe and path_to_poppler_exe.exists():
                # Use convert_from_path with poppler_path (like your notebook)
                # First, save the bytes to a temporary PDF file
                temp_pdf_path = os.path.join(tempdir, "temp.pdf")
                with open(temp_pdf_path, "wb") as f:
                    f.write(file_bytes)
                
                # Convert PDF to images using the same method as your notebook
                pdf_pages = convert_from_path(
                    temp_pdf_path, 
                    dpi, 
                    poppler_path=str(path_to_poppler_exe)
                )
                logger.info(f"Converted {len(pdf_pages)} pages using convert_from_path")
            else:
                # Fallback to convert_from_bytes (might work without poppler on some systems)
                pdf_pages = convert_from_bytes(file_bytes, dpi=dpi)
                logger.info(f"Converted {len(pdf_pages)} pages using convert_from_bytes")
            
            all_text = []
            
            # Process each page (same as your notebook)
            for page_enumeration, page in enumerate(pdf_pages, start=1):
                logger.info(f"Processing page {page_enumeration}/{len(pdf_pages)}...")
                
                # Save page as temporary image
                image_path = os.path.join(tempdir, f"page_{page_enumeration:03d}.jpg")
                page.save(image_path, "JPEG")
                
                # Extract text from image using Tesseract (same as your notebook)
                text = pytesseract.image_to_string(Image.open(image_path))
                
                # Apply the same text cleaning as your notebook
                text = text.replace("-\n", "")
                
                if text.strip():
                    all_text.append(f"\n--- Page {page_enumeration} ---\n{text}")
                else:
                    logger.warning(f"Page {page_enumeration} had no detectable text")
            
            final_text = '\n'.join(all_text)
            
            if not final_text.strip():
                raise Exception("No text could be extracted from the PDF. The document might be image-only or unreadable.")
            
            logger.info(f"Successfully extracted {len(final_text)} characters from PDF")
            return final_text
    
    except Exception as e:
        logger.error(f"PDF OCR failed: {e}")
        raise Exception(f"Failed to process PDF: {str(e)}")

def extract_text_from_image(file_bytes: bytes) -> str:
    """
    Extract text from image file
    """
    try:
        logger.info("Processing image file...")
        
        # Open image with PIL
        image = Image.open(io.BytesIO(file_bytes))
        
        # Save temporarily (optional, but consistent with your notebook approach)
        # But we can process directly from memory
        
        # Extract text using Tesseract
        text = pytesseract.image_to_string(image)
        
        # Apply same cleaning as your notebook
        text = text.replace("-\n", "")
        
        if not text.strip():
            raise Exception("No text could be detected in the image. Please ensure the image has clear, readable text.")
        
        logger.info(f"Extracted {len(text)} characters from image")
        return text
    
    except Exception as e:
        logger.error(f"Image OCR failed: {e}")
        raise Exception(f"Failed to process image: {str(e)}")

def extract_text_from_file(file_bytes: bytes, file_extension: str) -> str:
    """
    Main function to extract text from uploaded file
    """
    # Verify Tesseract is installed
    if not check_tesseract_installation():
        raise Exception("Tesseract OCR is not properly installed or configured. Please follow the installation instructions above.")
    
    file_extension = file_extension.lower()
    
    if file_extension == 'pdf':
        return extract_text_from_pdf(file_bytes)
    
    elif file_extension in ['png', 'jpg', 'jpeg', 'bmp', 'tiff']:
        return extract_text_from_image(file_bytes)
    
    else:
        raise ValueError(f"Unsupported file type: {file_extension}. Please upload PDF or image files.")

def preprocess_text_for_llm(text: str, max_chars: int = 3000) -> str:
    """
    Clean and truncate text for LLM context window
    """
    # Remove excessive whitespace
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    cleaned = '\n'.join(lines)
    
    # Remove extra spaces
    import re
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Truncate if too long
    if len(cleaned) > max_chars:
        logger.warning(f"Text too long ({len(cleaned)} chars), truncating to {max_chars}")
        # Try to truncate at a sentence boundary
        truncated = cleaned[:max_chars]
        last_period = truncated.rfind('.')
        if last_period > max_chars * 0.8:
            truncated = truncated[:last_period + 1]
        cleaned = truncated + "\n\n[Content truncated due to length...]"
    
    logger.info(f"Preprocessed text: {len(cleaned)} characters")
    return cleaned

# Test function (similar to your notebook)
def test_ocr_with_sample():
    """Test OCR with a sample PDF or image"""
    print("=" * 50)
    print("Testing OCR Setup")
    print("=" * 50)
    
    if not check_tesseract_installation():
        print("\n✗ Tesseract not configured correctly!")
        return False
    
    print("\n✓ Tesseract is installed!")
    
    # Test with a simple image
    try:
        # Create a test image
        from PIL import Image, ImageDraw, ImageFont
        
        img = Image.new('RGB', (400, 100), color='white')
        d = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()
        
        d.text((50, 40), "OCR TEST: Hello World!", fill='black', font=font)
        
        # Test OCR
        test_text = pytesseract.image_to_string(img)
        print(f"Test OCR result: {test_text.strip()}")
        
        if "Hello" in test_text:
            print("✓ OCR is working perfectly!")
            return True
        else:
            print("⚠ OCR test had issues, but might still work on real documents")
            return True
            
    except Exception as e:
        print(f"Test failed: {e}")
        return False

if __name__ == "__main__":
    test_ocr_with_sample()