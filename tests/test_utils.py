import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from scrapemaster.utils import (
    sanitize_filename,
    resolve_safe_path,
    clean_text,
    check_for_blocker,
    is_valid_url,
    generate_content_hash,
    calculate_reading_time,
    detect_content_type,
    extract_main_content_html,
    remove_noisy_elements
)
from bs4 import BeautifulSoup


class TestSanitizeFilename:
    """Security tests for filename sanitization."""
    
    def test_sanitize_traversal(self):
        """Should remove path traversal attempts."""
        assert sanitize_filename("../../../etc/passwd") == "etc_passwd"
        assert sanitize_filename("..\\..\\windows\\system32") == "windows_system32"
        assert sanitize_filename("....//....//file.txt") == "file.txt"
    
    def test_sanitize_hidden_files(self):
        """Should handle hidden files safely."""
        assert sanitize_filename(".env") == "hidden.env"
        assert sanitize_filename(".gitignore") == "hidden.gitignore"
    
    def test_sanitize_long_names(self):
        """Should enforce length limits."""
        long_name = "a" * 300 + ".txt"
        result = sanitize_filename(long_name, max_length=50)
        assert len(result) <= 50
        assert result.endswith(".txt")
    
    def test_sanitize_special_chars(self):
        """Should replace dangerous characters."""
        assert sanitize_filename("file<>name?.txt") == "file_name_.txt"
        assert sanitize_filename("file:name.txt") == "file_name.txt"
        assert sanitize_filename("file|name.txt") == "file_name.txt"
    
    def test_sanitize_empty(self):
        """Should handle empty input."""
        assert sanitize_filename("") == "download"
        assert sanitize_filename(None) == "download"


class TestResolveSafePath:
    """Security tests for path resolution."""
    
    def test_prevent_traversal(self):
        """Should block path traversal outside base directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            
            # Normal file should work
            safe = resolve_safe_path(base, "file.txt")
            assert safe.parent == base.resolve()
            
            # Traversal should raise ValueError
            with pytest.raises(ValueError, match="Path traversal detected"):
                resolve_safe_path(base, "../escape.txt")
            
            with pytest.raises(ValueError, match="Path traversal detected"):
                resolve_safe_path(base, "..\\..\\escape.txt")
    
    def test_filename_sanitization(self):
        """Should sanitize filename during resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            result = resolve_safe_path(base, "file<name>.txt")
            assert result.name == "file_name_.txt"


class TestCleanText:
    """Test text cleaning utilities."""
    
    def test_remove_control_chars(self):
        """Should remove non-printable characters."""
        dirty = "Hello\x00\x01\x02World"
        assert clean_text(dirty) == "HelloWorld"
    
    def test_normalize_whitespace(self):
        """Should collapse whitespace."""
        dirty = "Multiple  \n\t  spaces   "
        assert clean_text(dirty) == "Multiple spaces"
    
    def test_unicode_normalization(self):
        """Should handle unicode whitespace."""
        dirty = "Non-breaking\u00a0space"
        assert clean_text(dirty) == "Non-breaking space"


class TestBlockerDetection:
    """Test bot detection."""
    
    def test_cloudflare_detection(self):
        """Should detect Cloudflare."""
        assert check_for_blocker("<html>Cloudflare Ray ID</html>") is True
        assert check_for_blocker("CLOUDFLARE CHALLENGE") is True
        assert check_for_blocker("Just a moment...") is True
    
    def test_clean_page(self):
        """Should not flag legitimate content."""
        assert check_for_blocker("<html><body>Welcome to my blog</body></html>") is False
        assert check_for_blocker("Regular content here") is False


class TestURLValidation:
    """Security tests for URL validation."""
    
    def test_valid_urls(self):
        assert is_valid_url("https://example.com") is True
        assert is_valid_url("http://sub.example.com/path?query=1") is True
    
    def test_invalid_urls(self):
        assert is_valid_url("") is False
        assert is_valid_url(None) is False
        assert is_valid_url("javascript:alert(1)") is False
        assert is_valid_url("file:///etc/passwd") is False
        assert is_valid_url("data:text/html,<script>") is False


class TestContentHashing:
    """Test deduplication hashing."""
    
    def test_consistent_hash(self):
        content = "test content"
        hash1 = generate_content_hash(content)
        hash2 = generate_content_hash(content)
        assert hash1 == hash2
    
    def test_different_content(self):
        assert generate_content_hash("a") != generate_content_hash("b")
    
    def test_bytes_input(self):
        assert generate_content_hash(b"bytes") == generate_content_hash("bytes")


class TestReadingTime:
    """Test reading time calculation."""
    
    def test_calculation(self):
        # 200 words = 1 min
        text = " ".join(["word"] * 200)
        assert calculate_reading_time(text, wpm=200) == 1.0
        
        # 400 words = 2 min
        text = " ".join(["word"] * 400)
        assert calculate_reading_time(text, wpm=200) == 2.0


class TestContentTypeDetection:
    """Test content type detection."""
    
    def test_headers_detection(self):
        assert detect_content_type({"content-type": "text/html; charset=utf-8"}) == "html"
        assert detect_content_type({"content-type": "application/pdf"}) == "pdf"
        assert detect_content_type({"content-type": "image/jpeg"}) == "image"
    
    def test_url_fallback(self):
        assert detect_content_type(None, "https://example.com/file.pdf") == "pdf"
        assert detect_content_type(None, "https://example.com/image.jpg") == "image"


class TestHTMLProcessing:
    """Test BeautifulSoup utilities."""
    
    def test_extract_main_content(self):
        html = """
        <html><body>
            <nav>Navigation</nav>
            <main><article><p>Main content here with enough text to pass validation.</p></article></main>
            <footer>Footer</footer>
        </body></html>
        """
        soup = BeautifulSoup(html, 'lxml')
        element, selector = extract_main_content_html(soup)
        assert element is not None
        assert "Main content" in element.get_text()
    
    def test_remove_noisy_elements(self):
        html = """
        <div class="content">
            <p>Keep this</p>
            <nav>Remove this</nav>
            <script>Remove this</script>
        </div>
        """
        soup = BeautifulSoup(html, 'lxml')
        content = soup.find('div', class_='content')
        removed = remove_noisy_elements(content, ['nav', 'script'])
        assert removed == 2
        assert "Keep this" in content.get_text()
        assert "Remove this" not in content.get_text()