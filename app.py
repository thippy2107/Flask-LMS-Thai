# Import Libraries
import os
import secrets
# นำเข้า URL สำหรับการแยกส่วน URL ของฐานข้อมูล
from urllib.parse import urlparse 
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime

# --- Configuration ---
app = Flask(__name__)

# ตั้งค่าฐานข้อมูล: ใช้ Environment Variable (DATABASE_URL) สำหรับ Render/Production
# หากไม่พบ (เช่น รันบน Localhost) ให้ใช้ SQLite เพื่อความสะดวกในการทดสอบ
# **สำคัญ: Render จะกำหนด DATABASE_URL ให้เองเมื่อคุณสร้างฐานข้อมูล Postgres**
if os.environ.get("DATABASE_URL"):
    # Render จะให้ URL ในรูปแบบ postgres:// แต่ SQLAlchemy ต้องการ postgresql://
    uri = os.environ.get("DATABASE_URL")
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = uri
    # ไม่ต้องใช้ SQLite อีกต่อไป
    app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_DIR', 'student_submissions')
    # ต้องใช้ Gunicorn ในการทำงานจริง ดังนั้นต้องใช้ Environment Variable
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default_fallback_secret_key_for_prod')
else:
    # สำหรับการทดสอบบนเครื่อง Localhost (ใช้ SQLite)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///submission_project_prod.db' 
    app.config['UPLOAD_FOLDER'] = 'student_submissions'
    app.config['SECRET_KEY'] = 'your_super_secret_key_here' 

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Database Models (ไม่ต้องเปลี่ยน) ---

class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # คอลัมน์ teacher_id ต้องมีอยู่เพื่อไม่ให้เกิด OperationalError (ถูกเพิ่มแล้ว)
    teacher_id = db.Column(db.String(100), default='default_teacher')
    join_code = db.Column(db.String(10), unique=True, nullable=False)
    assignments = db.relationship('Assignment', backref='class_rel', lazy=True, cascade='all, delete-orphan') 

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    file_link = db.Column(db.String(500), nullable=True) 
    max_score = db.Column(db.Integer, default=100)
    due_date = db.Column(db.DateTime, nullable=True)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    submissions = db.relationship('Submission', backref='assignment_rel', lazy=True, cascade='all, delete-orphan')

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Integer, nullable=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)


# --- Setup Function ---

def setup_db():
    """สร้างฐานข้อมูลและตาราง รวมถึงข้อมูลเริ่มต้น"""
    with app.app_context():
        # ตรวจสอบว่ากำลังใช้ PostgreSQL (เมื่อ Deploy) หรือ SQLite (เมื่อ Local)
        if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
            print("Running in Production/Render mode with PostgreSQL. Skipping initial data creation.")
            # ใน Production เราจะสร้างตารางเสมอ แต่จะไม่สร้างข้อมูลเริ่มต้นซ้ำทุกครั้งที่รัน
            db.create_all()
        else:
            # สำหรับ Localhost/SQLite
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])

            db.create_all() 
            print("✅ Database tables created successfully (Local SQLite)!")
            
            # สร้างข้อมูลเริ่มต้น (ถ้ายังไม่มีชั้นเรียน)
            if Class.query.count() == 0:
                class1 = Class(name='คณิตศาสตร์ ม.3/1', join_code=secrets.token_hex(3).upper())
                db.session.add(class1)
                db.session.commit()
                
                assignment1 = Assignment(
                    title='แบบฝึกหัดเรื่อง พีทาโกรัส',
                    description='ส่งไฟล์ PDF ที่แสดงวิธีการคำนวณที่ถูกต้อง',
                    file_link='https://docs.google.com/document/d/example_pythagoras_link', 
                    max_score=20,
                    due_date=datetime.strptime('2025-12-15 23:59', '%Y-%m-%d %H:%M'),
                    class_id=class1.id
                )
                assignment2 = Assignment(
                    title='โจทย์ปัญหาเชิงซ้อน',
                    description='ส่งงานเขียนด้วยลายมือเท่านั้น',
                    file_link='https://example.com/complex_problems.pdf', 
                    max_score=50,
                    due_date=datetime.strptime('2025-11-20 18:00', '%Y-%m-%d %H:%M'),
                    class_id=class1.id
                )
                db.session.add_all([assignment1, assignment2])
                db.session.commit()
                print(f"✅ สร้างชั้นเรียน '{class1.name}' และ 2 ชิ้นงานเรียบร้อยแล้ว")
            else:
                print("Database already initialized with classes.")

# --- Routes (Teacher Side) ---

@app.route('/teacher')
def teacher_dashboard():
    """หน้า Dashboard หลักของครู แสดงรายการชั้นเรียนและงานมอบหมายทั้งหมด"""
    classes = Class.query.order_by(Class.id).all()
    return render_template('teacher_dashboard.html', classes=classes)

@app.route('/manage_classes', methods=['GET', 'POST'])
def manage_classes():
    """หน้าสำหรับเพิ่มและลบชั้นเรียน"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            class_name = request.form.get('class_name')
            if class_name:
                new_join_code = secrets.token_hex(3).upper() 
                new_class = Class(name=class_name, join_code=new_join_code)
                db.session.add(new_class)
                db.session.commit()
                flash(f'✅ สร้างชั้นเรียน "{class_name}" เรียบร้อยแล้ว รหัสเข้าร่วม: {new_join_code}', 'success')
            else:
                flash('❌ กรุณากรอกชื่อชั้นเรียน', 'error')
        
        elif action == 'delete':
            class_id_to_delete = request.form.get('class_id_to_delete')
            class_to_delete = Class.query.get(class_id_to_delete)
            if class_to_delete:
                db.session.delete(class_to_delete)
                db.session.commit()
                flash(f'🗑️ ลบชั้นเรียน "{class_to_delete.name}" และข้อมูลที่เกี่ยวข้องทั้งหมดเรียบร้อยแล้ว', 'warning')
            else:
                flash('❌ ไม่พบชั้นเรียนที่ต้องการลบ', 'error')

        return redirect(url_for('manage_classes'))

    classes = Class.query.order_by(Class.id).all()
    return render_template('manage_classes.html', classes=classes)


@app.route('/add_assignment', methods=['GET', 'POST'])
def add_assignment():
    """หน้าสำหรับเพิ่มงานมอบหมายใหม่"""
    classes = Class.query.all()
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        file_link = request.form.get('file_link') 
        max_score = request.form.get('max_score', type=int)
        due_date_str = request.form.get('due_date')
        class_id = request.form.get('class_id', type=int)
        
        if not all([title, max_score, class_id]):
            flash('❌ กรุณากรอกข้อมูลให้ครบถ้วน: ชื่อ, คะแนนเต็ม, และชั้นเรียน', 'error')
            return redirect(url_for('add_assignment'))

        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M') if due_date_str else None
            
            new_assignment = Assignment(
                title=title,
                description=description,
                file_link=file_link if file_link else None, 
                max_score=max_score,
                due_date=due_date,
                class_id=class_id
            )
            db.session.add(new_assignment)
            db.session.commit()
            flash(f'✅ สร้างงานมอบหมาย "{title}" เรียบร้อยแล้ว', 'success')
            return redirect(url_for('teacher_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ เกิดข้อผิดพลาดในการสร้างงาน: {e}', 'error')
            
    return render_template('add_assignment.html', classes=classes)


@app.route('/delete_assignment/<int:assignment_id>', methods=['POST'])
def delete_assignment(assignment_id):
    """ลบงานมอบหมายและงานที่ส่งมาทั้งหมดที่เกี่ยวข้อง"""
    assignment_to_delete = Assignment.query.get_or_404(assignment_id)
    
    try:
        db.session.delete(assignment_to_delete)
        db.session.commit()
        flash(f'🗑️ ลบงานมอบหมาย "{assignment_to_delete.title}" และงานที่ส่งมาทั้งหมดเรียบร้อยแล้ว', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ เกิดข้อผิดพลาดในการลบงาน: {e}', 'error')
        
    return redirect(url_for('teacher_dashboard'))


@app.route('/view_submissions/<int:assignment_id>')
def view_submissions(assignment_id):
    """หน้าสำหรับครูดูรายการงานที่ส่งมาและให้คะแนน"""
    assignment = Assignment.query.get_or_404(assignment_id)
    submissions = Submission.query.filter_by(assignment_id=assignment_id).order_by(Submission.submitted_at.desc()).all()
    
    return render_template('view_submissions.html', assignment=assignment, submissions=submissions)


@app.route('/grade_submission/<int:submission_id>', methods=['POST'])
def grade_submission(submission_id):
    """ประมวลผลการให้คะแนนงานที่ส่งมา"""
    submission = Submission.query.get_or_404(submission_id)
    
    try:
        score = request.form.get('score', type=int)
        max_score = submission.assignment_rel.max_score
        
        if score is None or score < 0 or score > max_score:
            flash(f'❌ คะแนนต้องอยู่ระหว่าง 0 ถึง {max_score}', 'error')
        else:
            submission.score = score
            db.session.commit()
            flash(f'✅ บันทึกคะแนน {score}/{max_score} สำหรับ "{submission.student_name}" เรียบร้อยแล้ว', 'success')
            
    except Exception as e:
        db.session.rollback()
        flash(f'❌ เกิดข้อผิดพลาดในการบันทึกคะแนน: {e}', 'error')

    return redirect(url_for('view_submissions', assignment_id=submission.assignment_id))


@app.route('/view_file/<filename>')
def view_file(filename):
    """อนุญาตให้ครูดาวน์โหลดหรือเปิดดูไฟล์ที่ส่งมา"""
    # ตรวจสอบเพื่อป้องกันการโจมตี Directory Traversal
    if '..' in filename or filename.startswith('/'):
        abort(404)
    # **ข้อควรระวัง:** ใน Production/Render ต้องใช้บริการจัดเก็บไฟล์ภายนอก (เช่น S3) 
    # แต่สำหรับ Render/Heroku ฟรี จะยังคงใช้ File System ได้
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# --- Routes (Student Side) ---

# หน้าแรกสำหรับนักเรียน (กรอกรหัสเข้าร่วม)
@app.route('/')
@app.route('/student_landing', methods=['GET'])
def student_landing():
    """หน้าแรกสำหรับนักเรียน เพื่อกรอกรหัสเข้าร่วม"""
    return render_template('student_landing.html')


@app.route('/student/assignments', methods=['POST'])
def student_view_assignments():
    """แสดงรายการงานมอบหมายทั้งหมดในชั้นเรียนที่นักเรียนกรอกรหัสเข้าร่วมมา"""
    join_code = request.form.get('join_code').strip().upper()

    if not join_code:
        flash('❌ กรุณากรอกรหัสเข้าร่วม', 'error')
        return redirect(url_for('student_landing'))

    class_obj = Class.query.filter_by(join_code=join_code).first()
    
    if not class_obj:
        flash('❌ ไม่พบรหัสเข้าร่วมนี้', 'error')
        return redirect(url_for('student_landing'))
    
    # ดึงงานมอบหมายทั้งหมดในชั้นเรียนนี้
    assignments = Assignment.query.filter_by(class_id=class_obj.id).order_by(Assignment.due_date.desc()).all()
    
    return render_template('list_assignments.html', 
                           class_info=class_obj, 
                           assignments=assignments,
                           datetime=datetime) 

@app.route('/submit/<int:assignment_id>', methods=['GET'])
def submission_form(assignment_id):
    """หน้าฟอร์มสำหรับนักเรียนใช้ส่งงาน"""
    
    assignment = Assignment.query.get(assignment_id)

    if not assignment:
        flash('❌ ไม่พบงานมอบหมายนี้', 'error')
        return redirect(url_for('student_landing')) 

    # โหลด Class Object ผ่าน backref 'class_rel'
    class_obj = assignment.class_rel 

    return render_template('submission_form.html', assignment=assignment, class_info=class_obj)


@app.route('/submit_submission/<int:assignment_id>', methods=['POST'])
def submit_submission(assignment_id):
    """ประมวลผลการส่งงานของนักเรียน"""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    student_name = request.form.get('student_name')
    if not student_name or 'file' not in request.files:
        flash('❌ กรุณากรอกชื่อและเลือกไฟล์', 'error')
        return redirect(url_for('submission_form', assignment_id=assignment_id))
        
    file = request.files['file']
    
    if file.filename == '':
        flash('❌ กรุณาเลือกไฟล์ที่จะอัปโหลด', 'error')
        return redirect(url_for('submission_form', assignment_id=assignment_id))

    if file:
        original_filename = secure_filename(file.filename)
        # ตรวจสอบว่ามี . ในชื่อไฟล์หรือไม่ ก่อนพยายามแยกนามสกุล
        file_extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'dat'
        
        # สร้างชื่อไฟล์ที่ไม่ซ้ำกันเพื่อเก็บในเซิร์ฟเวอร์
        unique_filename = f"{secure_filename(student_name)[:20]}_{assignment_id}_{secrets.token_hex(4)}.{file_extension}"

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        # ตรวจสอบว่ามีโฟลเดอร์สำหรับเก็บไฟล์หรือไม่
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
            
        file.save(filepath)
        
        # ตรวจสอบว่ามีการส่งงานนี้มาแล้วหรือไม่ (ใช้ชื่อนักเรียนและ ID งานมอบหมาย)
        # หากต้องการให้ส่งซ้ำได้ ให้ข้ามส่วนนี้
        
        new_submission = Submission(
            student_name=student_name,
            filename=unique_filename,
            assignment_id=assignment_id
        )
        db.session.add(new_submission)
        db.session.commit()

        flash(f'✅ ส่งงาน "{assignment.title}" เรียบร้อยแล้ว', 'success')
        return redirect(url_for('submission_form', assignment_id=assignment_id))

    flash('❌ เกิดข้อผิดพลาดในการส่งไฟล์', 'error')
    return redirect(url_for('submission_form', assignment_id=assignment_id))

# --- Application Run ---

if __name__ == '__main__':
    setup_db() 
    # ใช้ os.environ.get('PORT') สำหรับ Production Environment
    port = int(os.environ.get('PORT', 5000))
    # ใน Production ต้องใช้ Host 0.0.0.0
    app.run(debug=True, host='0.0.0.0', port=port)
