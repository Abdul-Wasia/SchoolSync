import requests
import json
import os
import logging
from pathlib import Path
from flask import current_app
from config import Config

logger = logging.getLogger(__name__)


def extract_material_text(file_path, max_chars=16000):
    """Extract readable text from supported course-material uploads only."""
    if not file_path:
        return ''

    relative_path = Path(file_path)
    if relative_path.is_absolute() or '..' in relative_path.parts:
        return ''
    if relative_path.parts[:2] == ('private', 'course_materials'):
        materials_root = Path(current_app.config.get(
            'PRIVATE_MATERIALS_FOLDER',
            os.path.join(current_app.instance_path, 'course_materials')
        )).resolve()
    elif relative_path.parts[:2] == ('uploads', 'materials'):
        materials_root = (Path(Config.UPLOAD_FOLDER) / 'materials').resolve()
    else:
        return ''

    material_path = (materials_root / relative_path.name).resolve()
    if os.path.commonpath([str(materials_root), str(material_path)]) != str(materials_root):
        return ''
    if not material_path.is_file():
        logger.warning('AI source file is missing from materials storage')
        return ''

    try:
        extension = material_path.suffix.lower()
        if extension == '.pdf':
            from pypdf import PdfReader
            parts = []
            char_count = 0
            for page_number, page in enumerate(PdfReader(str(material_path)).pages, start=1):
                page_text = page.extract_text() or ''
                if page_text:
                    page_content = f'Page {page_number}\n{page_text}'
                    parts.append(page_content)
                    char_count += len(page_content)
                if char_count >= max_chars:
                    break
            text = '\n\n'.join(parts)
        elif extension == '.docx':
            from docx import Document
            document = Document(str(material_path))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            parts.extend(
                ' | '.join(cell.text.strip() for cell in row.cells if cell.text.strip())
                for table in document.tables
                for row in table.rows
            )
            text = '\n'.join(parts)
        elif extension == '.pptx':
            from pptx import Presentation
            presentation = Presentation(str(material_path))
            parts = []
            char_count = 0
            for slide_number, slide in enumerate(presentation.slides, start=1):
                slide_text = '\n'.join(
                    shape.text for shape in slide.shapes
                    if getattr(shape, 'has_text_frame', False) and shape.text.strip()
                )
                if slide_text:
                    slide_content = f'Slide {slide_number}\n{slide_text}'
                    parts.append(slide_content)
                    char_count += len(slide_content)
                if char_count >= max_chars:
                    break
            text = '\n\n'.join(parts)
        elif extension in ('.txt', '.md', '.csv'):
            text = material_path.read_text(encoding='utf-8-sig', errors='ignore')
        else:
            return ''
    except Exception as exc:
        logger.warning('AI source text extraction failed (%s)', type(exc).__name__)
        return ''

    return text[:max_chars].strip()


def call_ai(prompt, max_tokens=1024):
    """
    Tries configured AI APIs in order. If one fails, tries the next.
    Returns the AI response text or an error message.
    """
    configured_keys = [
        Config.GROQ_API_KEY,
        Config.GEMINI_API_KEY,
        Config.OPENROUTER_API_KEY,
        Config.CLAUDE_API_KEY,
    ]
    if not any(configured_keys):
        return {
            'success': False,
            'text': 'AI is not configured. Set GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, or CLAUDE_API_KEY in your local .env file, then restart SchoolSync.',
            'provider': 'None'
        }

    failures = []

    # Try 1: Groq (fastest)
    if Config.GROQ_API_KEY:
        try:
            resp = requests.post(
                Config.GROQ_API_URL,
                headers={
                    'Authorization': f'Bearer {Config.GROQ_API_KEY}',
                    'Content-Type': 'application/json'
                },
                json={
                    'model': Config.GROQ_MODEL,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': max_tokens,
                    'temperature': 0.7
                },
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data['choices'][0]['message']['content']
                if text and text.strip():
                    print('[AI] Used: Groq')
                    return {'success': True, 'text': text, 'provider': 'Groq'}
            failures.append(f'Groq returned HTTP {resp.status_code}')
        except Exception:
            failures.append('Groq request failed')

    # Try 2: Google Gemini
    if Config.GEMINI_API_KEY:
        try:
            resp = requests.post(
                f"{Config.GEMINI_API_URL}?key={Config.GEMINI_API_KEY}",
                headers={'Content-Type': 'application/json'},
                json={
                    'contents': [{'parts': [{'text': prompt}]}],
                    'generationConfig': {'maxOutputTokens': max_tokens}
                },
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data['candidates'][0]['content']['parts'][0]['text']
                if text and text.strip():
                    print('[AI] Used: Gemini')
                    return {'success': True, 'text': text, 'provider': 'Gemini'}
            failures.append(f'Gemini returned HTTP {resp.status_code}')
        except Exception:
            failures.append('Gemini request failed')

    # Try 3: OpenRouter (backup)
    if Config.OPENROUTER_API_KEY:
        try:
            resp = requests.post(
                Config.OPENROUTER_API_URL,
                headers={
                    'Authorization': f'Bearer {Config.OPENROUTER_API_KEY}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': 'https://schoolsync.app',
                    'X-Title': 'SchoolSync'
                },
                json={
                    'model': Config.OPENROUTER_MODEL,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': max_tokens
                },
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data['choices'][0]['message']['content']
                if text and text.strip():
                    print('[AI] Used: OpenRouter')
                    return {'success': True, 'text': text, 'provider': 'OpenRouter'}
            failures.append(f'OpenRouter returned HTTP {resp.status_code}')
        except Exception:
            failures.append('OpenRouter request failed')

    if Config.CLAUDE_API_KEY:
        try:
            resp = requests.post(
                Config.CLAUDE_API_URL,
                headers={
                    'x-api-key': Config.CLAUDE_API_KEY,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json'
                },
                json={
                    'model': Config.CLAUDE_MODEL,
                    'max_tokens': max_tokens,
                    'messages': [{'role': 'user', 'content': prompt}]
                },
                timeout=20
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data['content'][0].get('text', '')
                if text and text.strip():
                    print('[AI] Used: Claude')
                    return {'success': True, 'text': text, 'provider': 'Claude'}
            failures.append(f'Claude returned HTTP {resp.status_code}')
        except Exception:
            failures.append('Claude request failed')

    return {
        'success': False,
        'text': 'Configured AI providers are unavailable. Check the API key, model access, quota, and internet connection.',
        'provider': ', '.join(failures) or 'Unavailable'
    }


def call_ai_json(prompt, max_tokens=1024):
    """
    Same as call_ai but tries to parse JSON from response.
    Returns parsed dict or None.
    """
    result = call_ai(prompt + '\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no explanation, just JSON.', max_tokens)
    if not result['success']:
        return None
    try:
        text = result['text'].strip()
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        return json.loads(text.strip())
    except Exception:
        return None
