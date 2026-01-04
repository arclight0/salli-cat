"""PDF utility functions."""

import logging
import re
from pathlib import Path

import pikepdf

logger = logging.getLogger(__name__)


def strip_manualslib_watermark(pdf_path: Path | str) -> bool:
    """
    Remove ManualsLib watermark from a PDF file in-place.

    The watermark consists of:
    - Text: "Downloaded from www.Manualslib.com manuals search engine"
    - A link annotation to manualslib.com

    Args:
        pdf_path: Path to the PDF file

    Returns:
        True if watermark was found and removed, False otherwise
    """
    pdf_path = Path(pdf_path)
    modified = False

    try:
        pdf = pikepdf.open(pdf_path, allow_overwriting_input=True)

        for page in pdf.pages:
            # Remove link annotations to manualslib.com
            if '/Annots' in page:
                new_annots = []
                for annot in list(page['/Annots']):
                    a = annot.get_object() if hasattr(annot, 'get_object') else annot
                    # Check if it's a link to manualslib
                    if '/A' in a and '/URI' in a['/A']:
                        uri = str(a['/A']['/URI'])
                        if 'manualslib.com' in uri.lower():
                            modified = True
                            continue  # Skip this annotation
                    new_annots.append(annot)

                if new_annots:
                    page['/Annots'] = pikepdf.Array(new_annots)
                else:
                    del page['/Annots']

            # Remove watermark from content stream
            contents = page.get('/Contents')
            if contents:
                if isinstance(contents, pikepdf.Array):
                    data = b''.join(c.read_bytes() for c in contents)
                else:
                    data = contents.read_bytes()

                text = data.decode('latin-1')

                # Pattern to match the watermark block
                # Matches the q...Q block containing manualslib watermark text
                pattern = r'q\s*\n0 0 \d+ \d+ re.*?manuals search engine.*?Q\s*\n?'
                cleaned = re.sub(pattern, '', text, flags=re.DOTALL)

                if cleaned != text:
                    modified = True
                    page['/Contents'] = pdf.make_stream(cleaned.encode('latin-1'))

        if modified:
            pdf.save(pdf_path)
            logger.info(f"Stripped ManualsLib watermark from {pdf_path}")

        pdf.close()

    except Exception as e:
        logger.error(f"Error stripping watermark from {pdf_path}: {e}")
        return False

    return modified
