import requests
import json
import os
import logging
from pathlib import Path
from flask import current_app
from config import Config

logger = logging.getLogger(__name__)


def extract_material_text(file_path, max_chars=16000):
    """Extract readable text from supported course-material uploads only.
    
    Prevents path traversal, enforces storage boundaries, and limits text
    extraction length to avoid memory exhaustion.
    """
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
    Tries configured AI APIs in fallback order: Groq -> Gemini -> OpenRouter -> Claude.
    Ensures safe error handling, avoids exposing API credentials, and prevents crashes.
    """
    configured_keys = [
        Config.GROQ_API_KEY,
        Config.GEMINI_API_KEY,
        Config.OPENROUTER_API_KEY,
        Config.CLAUDE_API_KEY,
    ]
    if not any(k and str(k).strip() for k in configured_keys):
        return {
            'success': False,
            'text': 'AI Assistant is not configured. Set GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, or CLAUDE_API_KEY in your local .env file, then restart SchoolSync.',
            'provider': 'None'
        }

    failures = []

    # 1. Try Groq
    if Config.GROQ_API_KEY and str(Config.GROQ_API_KEY).strip():
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
                choices = data.get('choices', [])
                if choices:
                    text = choices[0].get('message', {}).get('content', '')
                    if text and text.strip():
                        logger.info('AI call succeeded via Groq')
                        return {'success': True, 'text': text.strip(), 'provider': 'Groq'}
            failures.append(f'Groq HTTP {resp.status_code}')
        except Exception as exc:
            logger.warning('Groq request failed: %s', type(exc).__name__)
            failures.append('Groq request failed')

    # 2. Try Google Gemini
    if Config.GEMINI_API_KEY and str(Config.GEMINI_API_KEY).strip():
        try:
            # Mask API key in any error reporting
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
                candidates = data.get('candidates', [])
                if candidates:
                    parts = candidates[0].get('content', {}).get('parts', [])
                    if parts and 'text' in parts[0]:
                        text = parts[0]['text']
                        if text and text.strip():
                            logger.info('AI call succeeded via Gemini')
                            return {'success': True, 'text': text.strip(), 'provider': 'Gemini'}
            failures.append(f'Gemini HTTP {resp.status_code}')
        except Exception as exc:
            logger.warning('Gemini request failed: %s', type(exc).__name__)
            failures.append('Gemini request failed')

    # 3. Try OpenRouter
    if Config.OPENROUTER_API_KEY and str(Config.OPENROUTER_API_KEY).strip():
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
                choices = data.get('choices', [])
                if choices:
                    text = choices[0].get('message', {}).get('content', '')
                    if text and text.strip():
                        logger.info('AI call succeeded via OpenRouter')
                        return {'success': True, 'text': text.strip(), 'provider': 'OpenRouter'}
            failures.append(f'OpenRouter HTTP {resp.status_code}')
        except Exception as exc:
            logger.warning('OpenRouter request failed: %s', type(exc).__name__)
            failures.append('OpenRouter request failed')

    # 4. Try Anthropic Claude
    if Config.CLAUDE_API_KEY and str(Config.CLAUDE_API_KEY).strip():
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
                content = data.get('content', [])
                if content and isinstance(content, list):
                    text = content[0].get('text', '')
                    if text and text.strip():
                        logger.info('AI call succeeded via Claude')
                        return {'success': True, 'text': text.strip(), 'provider': 'Claude'}
            failures.append(f'Claude HTTP {resp.status_code}')
        except Exception as exc:
            logger.warning('Claude request failed: %s', type(exc).__name__)
            failures.append('Claude request failed')

    return {
        'success': False,
        'text': 'The AI Assistant is temporarily unavailable. Please check your network connection and verify API credentials in your .env configuration.',
        'provider': 'Unavailable'
    }


def call_ai_json(prompt, max_tokens=1024):
    """
    Calls AI provider requesting strict JSON format and safely parses the JSON response.
    Returns parsed dict/list or None without raising unhandled exceptions.
    """
    result = call_ai(
        prompt + '\n\nIMPORTANT: Return ONLY a valid JSON object. Do not include markdown fences, comments, or introductory text.',
        max_tokens=max_tokens
    )
    if not result or not result.get('success'):
        return None

    raw_text = (result.get('text') or '').strip()
    if not raw_text:
        return None

    # Handle markdown code blocks if the model wrapped output
    if '```' in raw_text:
        parts = raw_text.split('```')
        for block in parts[1:]:
            cleaned_block = block.strip()
            if cleaned_block.startswith('json'):
                cleaned_block = cleaned_block[4:].strip()
            try:
                return json.loads(cleaned_block)
            except Exception:
                continue

    # Attempt direct JSON parse
    try:
        return json.loads(raw_text)
    except Exception:
        # Extract potential JSON block between curly braces
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                return json.loads(raw_text[start_idx:end_idx + 1])
            except Exception:
                pass
        return None
