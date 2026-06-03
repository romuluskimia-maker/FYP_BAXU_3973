from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime

from config import Config
from models import db, User, Document, Question, StudentAnswer, StudentQuizSession, Feedback
from ocr_processor import extract_text_from_file, preprocess_text_for_llm
from question_generator import generate_mcq_with_distractors

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# Create database and default users
with app.app_context():
    db.create_all()
    
    # Create default users if they don't exist
    if not User.query.filter_by(username='teacher').first():
        teacher = User(
            username='teacher',
            password=generate_password_hash('teacher123'),
            role='teacher'
        )
        db.session.add(teacher)
    
    if not User.query.filter_by(username='student').first():
        student = User(
            username='student',
            password=generate_password_hash('student123'),
            role='student'
        )
        db.session.add(student)
        db.session.commit()

# ========== LOGIN FLOW ==========
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            
            # Redirect based on role
            if user.role == 'teacher':
                next_page = 'teacher_dashboard'
            else:
                next_page = 'student_dashboard'
            
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for(next_page))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

# ========== TEACHER FLOW (Based on your diagram) ==========

@app.route('/teacher/dashboard')
@login_required
def teacher_dashboard():
    if current_user.role != 'teacher':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    # Get statistics
    documents = Document.query.filter_by(teacher_id=current_user.id).all()
    pending_questions = Question.query.filter_by(teacher_feedback_status='pending', is_published=False).count()
    approved_questions = Question.query.filter_by(is_published=True).count()
    total_feedback = Feedback.query.count()
    
    return render_template('teacher/dashboard.html',
                         documents=documents,
                         pending_questions=pending_questions,
                         approved_questions=approved_questions,
                         total_feedback=total_feedback)

# Step 1: Upload lecture notes
@app.route('/teacher/upload', methods=['GET', 'POST'])
@login_required
def upload_notes():
    if current_user.role != 'teacher':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Process OCR
            file_ext = filename.rsplit('.', 1)[1].lower()
            with open(filepath, 'rb') as f:
                file_bytes = f.read()
            
            try:
                with app.app_context():
                    # Extract text via OCR
                    extracted_text = extract_text_from_file(file_bytes, file_ext)
                    cleaned_text = preprocess_text_for_llm(extracted_text)
                    
                    # Save document
                    doc = Document(
                        teacher_id=current_user.id,
                        filename=filename,
                        extracted_text=cleaned_text,
                        status='processing'
                    )
                    db.session.add(doc)
                    db.session.commit()
                    
                    # Store doc_id in session for generation
                    session['current_doc_id'] = doc.id
                    
                    flash(f'File uploaded and processed! Generating questions...', 'info')
                    return redirect(url_for('generate_questions_from_notes', doc_id=doc.id))
                    
            except Exception as e:
                flash(f'OCR failed: {str(e)}', 'danger')
                return redirect(request.url)
    
    return render_template('teacher/upload_notes.html')

# Step 2: Machine generates questions with distractors
@app.route('/teacher/generate/<doc_id>')
@login_required
def generate_questions_from_notes(doc_id):
    if current_user.role != 'teacher':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    doc = Document.query.get_or_404(doc_id)
    
    # Generate questions using Llama 3.2
    try:
        questions_data = generate_mcq_with_distractors(doc.extracted_text, 5)
        
        # Save generated questions
        for q_data in questions_data:
            question = Question(
                document_id=doc.id,
                question_text=q_data['question'],
                option_a=q_data['options'][0],
                option_b=q_data['options'][1],
                option_c=q_data['options'][2],
                option_d=q_data['options'][3],
                correct_answer=q_data['correct_answer'],
                explanation=q_data.get('explanation', ''),
                teacher_feedback_status='pending'  # Waiting for teacher feedback
            )
            db.session.add(question)
        
        # Update document status
        doc.status = 'completed'
        db.session.commit()
        
        flash(f'Successfully generated {len(questions_data)} questions!', 'success')
        
        # Redirect to review questions (get teacher feedback)
        return redirect(url_for('review_generated_questions', doc_id=doc.id))
        
    except Exception as e:
        flash(f'Generation failed: {str(e)}', 'danger')
        return redirect(url_for('teacher_dashboard'))

# Step 3: Show generated questions to get teacher's feedback
@app.route('/teacher/review/<doc_id>')
@login_required
def review_generated_questions(doc_id):
    if current_user.role != 'teacher':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    doc = Document.query.get_or_404(doc_id)
    questions = Question.query.filter_by(document_id=doc_id).all()
    
    return render_template('teacher/review_questions.html',
                         doc=doc,
                         questions=questions)

# Step 4: Question tuning with teachers (approve/reject/modify)
@app.route('/teacher/tune', methods=['GET', 'POST'])
@login_required
def tune_questions():
    if current_user.role != 'teacher':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Process tuning decisions
        action = request.form.get('action')
        
        if action == 'approve_all':
            # Approve all pending questions
            questions = Question.query.filter_by(teacher_feedback_status='pending').all()
            for q in questions:
                q.teacher_feedback_status = 'approved'
                q.is_published = True
                q.approved_at = datetime.utcnow()
            db.session.commit()
            flash(f'Approved {len(questions)} questions!', 'success')
            
        elif action == 'save_changes':
            # Save individual question edits
            for key, value in request.form.items():
                if key.startswith('question_'):
                    qid = key.split('_')[1]
                    question = Question.query.get(qid)
                    if question:
                        if 'text_' in key:
                            question.question_text = value
                        elif 'correct_' in key:
                            question.correct_answer = value
                        elif 'teacher_notes_' in key:
                            question.teacher_notes = value
                        elif 'status_' in key:
                            question.teacher_feedback_status = value
                            if value == 'approved':
                                question.is_published = True
                                question.approved_at = datetime.utcnow()
            db.session.commit()
            flash('Changes saved successfully!', 'success')
        
        return redirect(url_for('teacher_dashboard'))
    
    # GET request - show tuning interface
    pending_questions = Question.query.filter_by(teacher_feedback_status='pending').all()
    all_questions = Question.query.all()
    
    return render_template('teacher/tuning.html',
                         pending_questions=pending_questions,
                         all_questions=all_questions)

# Step 5: Save questions in server (already done when approved)
# Step 6: Gather feedback from students
@app.route('/teacher/view-feedback')
@login_required
def view_student_feedback():
    if current_user.role != 'teacher':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    all_feedback = Feedback.query.all()
    
    # Calculate statistics
    avg_rating = sum(f.rating for f in all_feedback) / len(all_feedback) if all_feedback else 0
    avg_quality = sum(f.question_quality for f in all_feedback if f.question_quality) / len(all_feedback) if all_feedback else 0
    avg_difficulty = sum(f.difficulty_rating for f in all_feedback if f.difficulty_rating) / len(all_feedback) if all_feedback else 0
    
    return render_template('teacher/view_feedback.html',
                         feedbacks=all_feedback,
                         avg_rating=avg_rating,
                         avg_quality=avg_quality,
                         avg_difficulty=avg_difficulty)

# ========== STUDENT FLOW (Based on your diagram) ==========

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    if current_user.role != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    # Get available questions (published by teacher)
    available_questions = Question.query.filter_by(is_published=True).all()
    
    # Check if student has already taken the quiz
    existing_session = StudentQuizSession.query.filter_by(
        student_id=current_user.id,
        completed_at=None
    ).first()
    
    # Get previous attempts
    completed_sessions = StudentQuizSession.query.filter_by(
        student_id=current_user.id
    ).filter(StudentQuizSession.completed_at.isnot(None)).all()
    
    return render_template('student/dashboard.html',
                         available_questions=available_questions,
                         existing_session=existing_session,
                         completed_sessions=completed_sessions)

# Step 1: Get questions made by teachers
@app.route('/student/take-quiz')
@login_required
def take_quiz():
    if current_user.role != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    # Get published questions
    questions = Question.query.filter_by(is_published=True).all()
    
    if not questions:
        flash('No questions available yet. Please check back later.', 'warning')
        return redirect(url_for('student_dashboard'))
    
    # Create or get existing session
    session_obj = StudentQuizSession.query.filter_by(
        student_id=current_user.id,
        completed_at=None
    ).first()
    
    if not session_obj:
        session_obj = StudentQuizSession(student_id=current_user.id)
        db.session.add(session_obj)
        db.session.commit()
    
    return render_template('student/take_quiz.html',
                         questions=questions,
                         session_id=session_obj.id)

# Step 2: Student starts answering questions (handled via AJAX)
@app.route('/student/submit-answer', methods=['POST'])
@login_required
def submit_answer():
    if current_user.role != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    question_id = data.get('question_id')
    selected_option = data.get('selected_option')
    session_id = data.get('session_id')
    
    question = Question.query.get(question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404
    
    # Check if already answered
    existing = StudentAnswer.query.filter_by(
        student_id=current_user.id,
        question_id=question_id
    ).first()
    
    if existing:
        return jsonify({'error': 'Already answered'}), 400
    
    # Evaluate answer
    is_correct = (selected_option == question.correct_answer)
    
    # Save answer
    answer = StudentAnswer(
        student_id=current_user.id,
        question_id=question_id,
        selected_option=selected_option,
        is_correct=is_correct,
        points_earned=1 if is_correct else 0,
        points_possible=1
    )
    db.session.add(answer)
    
    # Update session score
    session_obj = StudentQuizSession.query.get(session_id)
    if session_obj:
        session_obj.total_score += (1 if is_correct else 0)
        session_obj.total_possible += 1
        db.session.commit()
    
    # Return immediate feedback
    return jsonify({
        'correct': is_correct,
        'correct_answer': question.correct_answer,
        'explanation': question.explanation,
        'options': {
            'A': question.option_a,
            'B': question.option_b,
            'C': question.option_c,
            'D': question.option_d
        }
    })

# Step 3: Machine evaluation of student's performance
@app.route('/student/complete-quiz/<session_id>', methods=['POST'])
@login_required
def complete_quiz(session_id):
    if current_user.role != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    session_obj = StudentQuizSession.query.get_or_404(session_id)
    session_obj.completed_at = datetime.utcnow()
    db.session.commit()
    
    flash('Quiz completed! View your performance below.', 'success')
    return redirect(url_for('view_performance', session_id=session_id))

# Step 4: Show score and explanation for every question and answer
@app.route('/student/performance/<session_id>')
@login_required
def view_performance(session_id):
    if current_user.role != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    session_obj = StudentQuizSession.query.get_or_404(session_id)
    
    # Get all answers from this session
    # Note: Since we don't link answers directly to sessions yet, get by student and time
    answers = StudentAnswer.query.filter_by(student_id=current_user.id).order_by(StudentAnswer.answered_at.desc()).limit(
        session_obj.total_possible
    ).all()
    
    # Build detailed results
    results = []
    for answer in answers:
        question = Question.query.get(answer.question_id)
        results.append({
            'question_text': question.question_text,
            'student_answer': answer.selected_option,
            'correct_answer': question.correct_answer,
            'is_correct': answer.is_correct,
            'explanation': question.explanation,
            'options': {
                'A': question.option_a,
                'B': question.option_b,
                'C': question.option_c,
                'D': question.option_d
            }
        })
    
    percentage = (session_obj.total_score / session_obj.total_possible * 100) if session_obj.total_possible > 0 else 0
    
    return render_template('student/performance.html',
                         session=session_obj,
                         results=results,
                         percentage=percentage)

# Step 5: Gather feedback from students
@app.route('/student/give-feedback', methods=['GET', 'POST'])
@login_required
def give_feedback():
    if current_user.role != 'student':
        flash('Access denied', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        rating = int(request.form.get('rating', 3))
        comment = request.form.get('comment', '')
        question_quality = int(request.form.get('question_quality', 3))
        difficulty_rating = int(request.form.get('difficulty_rating', 3))
        
        feedback = Feedback(
            student_id=current_user.id,
            rating=rating,
            comment=comment,
            question_quality=question_quality,
            difficulty_rating=difficulty_rating
        )
        db.session.add(feedback)
        db.session.commit()
        
        flash('Thank you for your feedback! It will help improve future questions.', 'success')
        return redirect(url_for('student_dashboard'))
    
    return render_template('student/give_feedback.html')

# ========== HELPER ROUTES ==========
@app.route('/api/questions/<qid>', methods=['PUT'])
@login_required
def api_update_question(qid):
    if current_user.role != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    
    question = Question.query.get_or_404(qid)
    data = request.json
    
    question.question_text = data.get('question_text', question.question_text)
    question.option_a = data.get('option_a', question.option_a)
    question.option_b = data.get('option_b', question.option_b)
    question.option_c = data.get('option_c', question.option_c)
    question.option_d = data.get('option_d', question.option_d)
    question.correct_answer = data.get('correct_answer', question.correct_answer)
    question.explanation = data.get('explanation', question.explanation)
    question.teacher_notes = data.get('teacher_notes', question.teacher_notes)
    question.teacher_feedback_status = data.get('status', question.teacher_feedback_status)
    
    if question.teacher_feedback_status == 'approved' and not question.is_published:
        question.is_published = True
        question.approved_at = datetime.utcnow()
    
    db.session.commit()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)