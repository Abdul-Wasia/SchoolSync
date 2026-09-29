import requests
import json
from config import Config


def call_ai(prompt, max_tokens=1024):
    """
    Tries 3 AI APIs in order. If one fails, tries the next.
    Returns the AI response text or an error message.
    """

    # Try 1: Groq (fastest)
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
            if text and len(text.strip()) > 10:
                print('[AI] Used: Groq')
                return {'success': True, 'text': text, 'provider': 'Groq'}
    except Exception as e:
        print(f'[AI] Groq failed: {e}')

    # Try 2: Google Gemini
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
            if text and len(text.strip()) > 10:
                print('[AI] Used: Gemini')
                return {'success': True, 'text': text, 'provider': 'Gemini'}
    except Exception as e:
        print(f'[AI] Gemini failed: {e}')

    # Try 3: OpenRouter (backup)
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
            if text and len(text.strip()) > 10:
                print('[AI] Used: OpenRouter')
                return {'success': True, 'text': text, 'provider': 'OpenRouter'}
    except Exception as e:
        print(f'[AI] OpenRouter failed: {e}')

    return {
        'success': False,
        'text': 'AI service is currently unavailable. Please check your API keys in config.py and try again.',
        'provider': 'None'
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
