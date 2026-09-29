from flask import Blueprint, render_template, request, jsonify, session
from database.connection import query
from functools import wraps
from routes.ai_helper import call_ai, call_ai_json

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')


def login_required_ai(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': 'Not logged in'}), 401
        return f(*args, **kwargs)
    return wrapper


@ai_bp.route('/summarizer')
def summarizer_page():
    subjects = query('SELECT * FROM subjects ORDER BY subject_name', fetch=True) or []
    return render_template('ai/summarizer.html', subjects=subjects)


@ai_bp.route('/summarize', methods=['POST'])
@login_required_ai
def summarize():
    data = request.get_json(silent=True) or {}
    topic = (data.get('topic') or '').strip()
    subject = (data.get('subject') or 'General').strip()
    level = (data.get('level') or 'Grade 8').strip()

    if not topic:
        return jsonify({'success': False, 'error': 'Please enter a topic'}), 400

    prompt = f"""You are a helpful school teacher.
Summarize the topic \"{topic}\" for {level} students studying {subject}.

Provide:
## Simple Summary
Write 3-4 clear sentences explaining the topic simply.

## Key Points
List 5 important points as bullet points.

## Real World Example
Give one relatable real-world example a student can understand.

## Remember This
One sentence the student should memorize.

Keep the language simple, clear, and educational."""

    result = call_ai(prompt, max_tokens=800)
    return jsonify({
        'success': result['success'],
        'summary': result['text'],
        'provider': result.get('provider', 'Unknown')
    })


@ai_bp.route('/quiz')
def quiz_page():
    subjects = query('SELECT * FROM subjects ORDER BY subject_name', fetch=True) or []
    return render_template('ai/quiz.html', subjects=subjects)


@ai_bp.route('/generate-quiz', methods=['POST'])
@login_required_ai
def generate_quiz():
    data = request.get_json(silent=True) or {}
    topic = (data.get('topic') or '').strip()
    subject = (data.get('subject') or 'General').strip()
    num_q = int(data.get('num_questions', 5) or 5)

    if not topic:
        return jsonify({'success': False, 'error': 'Please enter a topic'}), 400

    prompt = f"""Generate {num_q} multiple choice questions about \"{topic}\" for {subject} students.

Return ONLY this JSON format, nothing else:
{{
  "questions": [
    {{
      "question": "What is ...?",
      "options": ["A) option1", "B) option2", "C) option3", "D) option4"],
      "correct": "A",
      "explanation": "Because ..."
    }}
  ]
}}"""

    result = call_ai_json(prompt, max_tokens=1500)
    if result and 'questions' in result:
        return jsonify({'success': True, 'questions': result['questions']})

    plain = call_ai(prompt, max_tokens=1500)
    return jsonify({'success': False, 'error': 'Could not generate quiz. Try a different topic.'})


@ai_bp.route('/chat')
def chat_page():
    subjects = query('SELECT * FROM subjects ORDER BY subject_name', fetch=True) or []
    return render_template('ai/chat.html', subjects=subjects)


@ai_bp.route('/chat/send', methods=['POST'])
@login_required_ai
def chat_send():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    subject = (data.get('subject') or 'General').strip()
    history = data.get('history', [])

    if not message:
        return jsonify({'success': False, 'error': 'Empty message'}), 400

    context = '\n'.join([
        f"{'Student' if h.get('role') == 'user' else 'Teacher'}: {h.get('content', '')}"
        for h in history[-6:]
    ])

    prompt = f"""You are a friendly and helpful school teacher 
assistant for SchoolSync. You are helping a student with {subject}.

Previous conversation:
{context}

Student asks: {message}

Reply helpfully, clearly, and simply. 
If the question is not about education, politely say 
you can only help with school subjects.
Keep your reply under 200 words."""

    result = call_ai(prompt, max_tokens=400)
    return jsonify({
        'success': result['success'],
        'reply': result['text'],
        'provider': result.get('provider', '')
    })


@ai_bp.route('/study-planner')
def study_planner_page():
    subjects = query('SELECT * FROM subjects ORDER BY subject_name', fetch=True) or []
    return render_template('ai/study_plan.html', subjects=subjects)


@ai_bp.route('/generate-plan', methods=['POST'])
@login_required_ai
def generate_plan():
    data = request.get_json(silent=True) or {}
    exam_date = (data.get('exam_date') or '').strip()
    subjects = data.get('subjects') or []
    hours = data.get('hours_per_day', 2)

    if not exam_date or not subjects:
        return jsonify({'success': False, 'error': 'Please fill all fields'}), 400

    from datetime import date
    today = date.today().strftime('%Y-%m-%d')
    subj_str = ', '.join(subjects)

    prompt = f"""Create a daily study plan for a school student.

Start date: {today}
Exam date: {exam_date}
Subjects to cover: {subj_str}
Available hours per day: {hours}

Make a week-by-week plan.
For each week show: which subjects to focus on and what to study.
Last 3 days before exam: only revision.
Format as a clear table using markdown.
Keep it practical and achievable for a school student."""

    result = call_ai(prompt, max_tokens=1000)
    return jsonify({
        'success': result['success'],
        'plan': result['text'],
        'provider': result.get('provider', '')
    })


@ai_bp.route('/status')
def ai_status():
    """Check which AI APIs are working"""
    statuses = []

    try:
        from config import Config
        import requests as req
        r = req.post(
            Config.GROQ_API_URL,
            headers={'Authorization': f'Bearer {Config.GROQ_API_KEY}', 'Content-Type': 'application/json'},
            json={'model': Config.GROQ_MODEL, 'messages': [{'role': 'user', 'content': 'Say OK'}], 'max_tokens': 5},
            timeout=8
        )
        statuses.append({'name': 'Groq', 'status': 'online' if r.status_code == 200 else 'error', 'code': r.status_code})
    except Exception:
        statuses.append({'name': 'Groq', 'status': 'offline', 'code': 0})

    try:
        import requests as req
        r = req.post(
            f"{Config.GEMINI_API_URL}?key={Config.GEMINI_API_KEY}",
            headers={'Content-Type': 'application/json'},
            json={'contents': [{'parts': [{'text': 'Say OK'}]}], 'generationConfig': {'maxOutputTokens': 5}},
            timeout=8
        )
        statuses.append({'name': 'Gemini', 'status': 'online' if r.status_code == 200 else 'error', 'code': r.status_code})
    except Exception:
        statuses.append({'name': 'Gemini', 'status': 'offline', 'code': 0})

    try:
        import requests as req
        r = req.post(
            Config.OPENROUTER_API_URL,
            headers={'Authorization': f'Bearer {Config.OPENROUTER_API_KEY}', 'Content-Type': 'application/json'},
            json={'model': Config.OPENROUTER_MODEL, 'messages': [{'role': 'user', 'content': 'Say OK'}], 'max_tokens': 5},
            timeout=8
        )
        statuses.append({'name': 'OpenRouter', 'status': 'online' if r.status_code == 200 else 'error', 'code': r.status_code})
    except Exception:
        statuses.append({'name': 'OpenRouter', 'status': 'offline', 'code': 0})

    return jsonify({'apis': statuses})


@ai_bp.route('/generate-report', methods=['POST'])
def generate_report():
    data = request.get_json(silent=True) or {}
    report_data = data.get('report_data') or {
        'overall_attendance': 'N/A',
        'top_sections': [],
        'bottom_sections': [],
        'teacher_absences': [],
        'low_grades': []
    }

    prompt = (
        "Write a formal school performance report based on this data: "
        f"{report_data}. Include: Executive Summary, Attendance Analysis, Academic Performance, "
        "Teacher Performance, Recommendations. Use professional language."
    )
    result = call_ai(prompt, max_tokens=1200)
    if not result['success']:
        return jsonify({'success': False, 'message': 'AI failed while generating the report.'}), 500
    return jsonify({'success': True, 'report': result['text']})


@ai_bp.route('/write-announcement', methods=['POST'])
def write_announcement():
    payload = request.get_json(silent=True) or {}
    topic = (payload.get('topic') or '').strip()
    target = (payload.get('target') or 'All Students').strip()
    if not topic:
        return jsonify({'success': False, 'message': 'Topic is required.'}), 400

    prompt = (
        f"Write a formal school announcement about {topic} for {target}. "
        "Include date placeholder, venue, and important instructions. Keep it professional."
    )
    result = call_ai(prompt, max_tokens=800)
    if not result['success']:
        return jsonify({'success': False, 'message': 'AI failed while generating the announcement.'}), 500
    return jsonify({'success': True, 'announcement': result['text']})
