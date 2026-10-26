import io
import uuid
import zipfile
from pathlib import Path

from werkzeug.utils import secure_filename


class UploadValidationError(ValueError):
    pass


def _content_matches(extension, content):
    if extension == 'pdf':
        return content.startswith(b'%PDF-')
    if extension == 'png':
        return content.startswith(b'\x89PNG\r\n\x1a\n')
    if extension in {'jpg', 'jpeg'}:
        return content.startswith(b'\xff\xd8\xff')
    if extension == 'docx':
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return False
        return '[Content_Types].xml' in names and 'word/document.xml' in names
    if extension == 'zip':
        return zipfile.is_zipfile(io.BytesIO(content))
    return False


def save_validated_upload(upload, destination, allowed_extensions, max_bytes):
    original_name = upload.filename
    if (
        not original_name
        or len(original_name) > 255
        or '/' in original_name
        or '\\' in original_name
        or '\x00' in original_name
    ):
        raise UploadValidationError('Choose a valid filename.')

    safe_name = secure_filename(original_name)
    if not safe_name or '.' not in safe_name:
        raise UploadValidationError('Choose a file with a supported extension.')

    extension = safe_name.rsplit('.', 1)[1].lower()
    if extension not in allowed_extensions:
        raise UploadValidationError('This file type is not allowed.')

    content = upload.stream.read(max_bytes + 1)
    if not content:
        raise UploadValidationError('The uploaded file is empty.')
    if len(content) > max_bytes:
        raise UploadValidationError(f'Files must be {max_bytes // (1024 * 1024)} MB or smaller.')
    if not _content_matches(extension, content):
        raise UploadValidationError('The file content does not match its extension.')

    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.{extension}'
    file_path = destination / filename
    try:
        with file_path.open('xb') as saved_file:
            saved_file.write(content)
    except FileExistsError:
        raise OSError('Could not allocate a unique upload filename.') from None

    return filename
