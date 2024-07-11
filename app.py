from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response
from werkzeug.utils import secure_filename
import os
import secrets
import bcrypt
import cv2
import time
import threading
from datetime import datetime, timedelta
import numpy as np
from model import detect_and_track_cars, model, active_cars, timers, alarms, send_whatsapp_message
from flask_mysqldb import MySQL
import MySQLdb.cursors

app = Flask(__name__)
# Generate a secret key
app.secret_key = secrets.token_hex(16)
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'dropoffzone'
mysql = MySQL(app)

app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

video_source = None
cap = None
paused = False
last_frame = None
default_zone = np.array([(440, 290), (490, 300), (410, 380), (330, 360)])
zone = default_zone.copy()



def get_alarm_threshold():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT waktu_alarm FROM pengaturan LIMIT 1")
    result = cursor.fetchone()
    if result:
        return result['waktu_alarm']
    return 25  # Default value if not found

def update_alarm_threshold(new_value):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("UPDATE pengaturan SET waktu_alarm = %s LIMIT 1", (new_value,))
    mysql.connection.commit()

# Set alarm value inside the application context
with app.app_context():
    ALARM_THRESHOLD = get_alarm_threshold()

# Clear session
@app.route('/')
def index():
    session.clear()
    return render_template('index.html')

# Fungsi untuk menghapus file setelah satu hari
def schedule_file_deletion(file_path):
    def delete_file(file_path):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"File {file_path} telah dihapus.")
            else:
                print(f"File {file_path} tidak ditemukan.")
        except Exception as e:
            print(f"Gagal menghapus file {file_path}: {str(e)}")

    # Jadwalkan penghapusan setelah satu hari
    deletion_time = datetime.now() + timedelta(days=1)
    threading.Timer((deletion_time - datetime.now()).total_seconds(), delete_file, args=[file_path]).start()

@app.route('/upload_video', methods=['POST'])
def upload_video():
    global video_source, cap, paused
    video_file = request.files.get('videoFile')
    if video_file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], video_file.filename)
        video_file.save(file_path)
        video_source = file_path
        # Jadwalkan penghapusan file
        schedule_file_deletion(file_path)
    else:
        video_source = request.form.get('videoSource')

    cap = cv2.VideoCapture(video_source)
    paused = False
    return jsonify({'video_source': video_source})

@app.route('/toggle_video', methods=['POST'])
def toggle_video():
    global paused
    paused = not paused
    return jsonify({'paused': paused})

@app.route('/reset_video', methods=['POST'])
def reset_video():
    global cap, paused, zone
    video_source = None
    cap = None
    paused = False
    zone = default_zone.copy()
    active_cars.clear()
    timers.clear()
    alarms.clear()
    return '', 204

@app.route('/set_zone', methods=['POST'])
def set_zone():
    global zone
    data = request.get_json()
    zone = np.array(data['zone'])
    return '', 204

def insert_dropoff(id_mobil, waktu_masuk, waktu_keluar=None):
    tanggal = waktu_masuk.date()
    with app.app_context():
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO datamobil (id_mobil, waktu_masuk, waktu_keluar, tanggal) VALUES (%s, %s, %s, %s)",
                    (id_mobil, waktu_masuk, waktu_keluar, tanggal))
        mysql.connection.commit()
        cur.close()

def update_dropoff(id_mobil, waktu_keluar):
    with app.app_context():
        cur = mysql.connection.cursor()
        cur.execute("UPDATE datamobil SET waktu_keluar = %s WHERE id_mobil = %s AND waktu_keluar IS NULL", (waktu_keluar, id_mobil))
        mysql.connection.commit()
        cur.close()

def get_security_contacts():
    with app.app_context():
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT no_wa FROM security')
        contacts = cursor.fetchall()
        return [contact['no_wa'] for contact in contacts]

def gen_frames():
    global cap, paused, last_frame, zone
    window_width, window_height = 800, 600

    while True:
        if paused:
            if last_frame is not None:
                ret, buffer = cv2.imencode('.jpg', last_frame)
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            continue

        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (window_width, window_height))
        contacts = get_security_contacts()  # Get kontak
        detect_and_track_cars(frame, model, zone, active_cars, timers, alarms, insert_dropoff, update_dropoff, contacts, ALARM_THRESHOLD)

        
        last_frame = frame

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# Route for logout
@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/login', methods=['POST'])
def login():
    # Periksa jenis konten permintaan
    if request.headers['Content-Type'] == 'application/json':
        # Jika permintaan adalah JSON
        data = request.get_json()
        username = data['username']
        password = data['password']
    else:
        # Jika permintaan adalah form-urlencoded
        username = request.form['username']
        password = request.form['password']

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()

    if user and bcrypt.checkpw(password.encode('utf-8'), user[3].encode('utf-8')):
        session['user'] = username
        flash('Login successful!', 'success')
        if request.is_json:
            return jsonify(message="Login successful!")
        else:
            return redirect(url_for('dashboard'))
    else:
        flash('Invalid username or password', 'danger')
        if request.is_json:
            return jsonify(error="Invalid username or password"), 401
        else:
            return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Periksa jenis konten permintaan
        if request.headers['Content-Type'] == 'application/json':
            # Jika permintaan adalah JSON
            data = request.get_json()
            username = data['username']
            nomer_wa = data['nomer_wa']
            password = data['password']
            repeat_password = data['repeat_password']
        else:
            # Jika permintaan adalah form-urlencoded
            username = request.form['username']
            nomer_wa = request.form['nomer_wa']
            password = request.form['password']
            repeat_password = request.form['repeat_password']

        if password != repeat_password:
            if request.headers['Content-Type'] == 'application/json':
                return jsonify(error='Passwords do not match'), 400  # Return JSON response with error message and status code
            else:
                flash('Passwords do not match!', 'danger')
                return redirect(url_for('register'))

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO users (username, nomer_wa, password) VALUES (%s, %s, %s)", 
                    (username, nomer_wa, hashed_password.decode('utf-8')))
        mysql.connection.commit()
        cur.close()
        
        if request.headers['Content-Type'] == 'application/json':
            return jsonify(message='You have successfully registered!'), 201  # Return JSON response with success message and status code
        else:
            flash('You have successfully registered!', 'success')
            return redirect(url_for('index'))

    return render_template('register.html')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user' in session:
        if request.method == 'POST':
            new_waktu_alarm = request.form['waktu_alarm']
            update_alarm_threshold(new_waktu_alarm)
            flash("Alarm threshold updated successfully!")
            return redirect(url_for('dashboard'))
    else:
        flash("You need to log in first!", "error")
        return redirect(url_for('index'))

    current_waktu_alarm = get_alarm_threshold()
    return render_template('dashboard.html', current_waktu_alarm=current_waktu_alarm)

@app.route('/databarchar')
def databarchar():
    if 'user' in session:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Menghitung tanggal 5 bulan yang lalu
        today = datetime.today()
        five_months_ago = today - timedelta(days=5*30)  # Menggunakan 30 hari per bulan untuk perkiraan
        
        # Memperbaiki format tanggal untuk query SQL
        start_date = five_months_ago.strftime('%Y-%m-%d')

        query = '''
        SELECT MONTH(waktu_masuk) AS month, COUNT(*) AS count
        FROM datamobil
        WHERE waktu_masuk >= %s
        GROUP BY MONTH(waktu_masuk)
        ORDER BY month
        '''
        cursor.execute(query, (start_date,))
        data = cursor.fetchall()

        # Menyiapkan data untuk chart
        months = ["Januari","Februari","Maret","April", "Mei", "Juni", "Juli","Agustus","September","Oktober","November","Desember"]
        counts = [0] * 5

        # Mendapatkan bulan-bulan dari 5 bulan lalu hingga sekarang
        month_indexes = [(today.month - i) % 12 for i in range(5)]
        month_indexes = month_indexes[::-1]  # Mengurutkan dari 5 bulan lalu ke bulan sekarang

        for row in data:
            if row['month'] in month_indexes:
                month_index = month_indexes.index(row['month'])
                counts[month_index] = row['count']

        selected_months = [months[(today.month - i - 1) % 12] for i in range(5)]
        selected_months = selected_months[::-1]

        return render_template('laporan-trafik.html', months=selected_months, counts=counts)
    else:
        return redirect(url_for('index'))

@app.route('/api/piechart-data')
def piechart_data():
    filter_type = request.args.get('filter', 'daily')
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if filter_type == 'daily':
        cursor.execute("""
            SELECT 
                SUM(pelanggaran = 1) AS pelanggaran,
                SUM(pelanggaran = 0) AS taat 
            FROM datamobil
            WHERE DATE(waktu_masuk) = CURDATE()
        """)
    elif filter_type == 'monthly':
        cursor.execute("""
            SELECT 
                SUM(pelanggaran = 1) AS pelanggaran,
                SUM(pelanggaran = 0) AS taat 
            FROM datamobil
            WHERE YEAR(waktu_masuk) = YEAR(CURDATE()) AND MONTH(waktu_masuk) = MONTH(CURDATE())
        """)
    elif filter_type == 'yearly':
        cursor.execute("""
            SELECT 
                SUM(pelanggaran = 1) AS pelanggaran,
                SUM(pelanggaran = 0) AS taat 
            FROM datamobil
            WHERE YEAR(waktu_masuk) = YEAR(CURDATE())
        """)

    data = cursor.fetchone()
    cursor.close()

    # Jika data kosong untuk filter harian, kirimkan pesan "Tidak ada data untuk hari ini"
    if filter_type == 'daily' and data['pelanggaran'] is None and data['taat'] is None:
        return jsonify({'message': 'Tidak ada data untuk hari ini'})

    return jsonify(data)
    
@app.route('/datahistori')
def datahistori():
    if 'user' in session:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM datamobil ORDER BY waktu_masuk DESC')
        data = cursor.fetchall()
        return render_template('histori.html', datamobil=data)
    else:
        return redirect(url_for('index'))
    
@app.route('/add_mobil', methods=['POST'])
def add_mobil():
    if request.method == 'POST':
        id_mobil = request.form['id_mobil']
        waktu_masuk = request.form['waktu_masuk']
        waktu_keluar = request.form['waktu_keluar']
        tanggal = request.form['tanggal']
        cursor = mysql.connection.cursor()
        cursor.execute('INSERT INTO datamobil (id_mobil, waktu_masuk, waktu_keluar, tanggal) VALUES (%s, %s, %s, %s)', (id_mobil, waktu_masuk, waktu_keluar, tanggal))
        mysql.connection.commit()
        flash('Data added successfully!')
        return redirect(url_for('datahistori'))

@app.route('/update_mobil/<int:id>', methods=['POST'])
def update_mobil(id):
    if request.method == 'POST':
        id_mobil = request.form['id_mobil']
        waktu_masuk = request.form['waktu_masuk']
        waktu_keluar = request.form['waktu_keluar']
        tanggal = request.form['tanggal']
        cursor = mysql.connection.cursor()
        cursor.execute('UPDATE datamobil SET id_mobil = %s, waktu_masuk = %s, waktu_keluar = %s, tanggal = %s WHERE id = %s', (id_mobil, waktu_masuk, waktu_keluar, tanggal, id))
        mysql.connection.commit()
        flash('Data updated successfully!')
        return redirect(url_for('datahistori'))

@app.route('/delete_mobil/<int:id>')
def delete_mobil(id):
    cursor = mysql.connection.cursor()
    cursor.execute('DELETE FROM datamobil WHERE id = %s', (id,))
    mysql.connection.commit()
    flash('Data deleted successfully!')
    return redirect(url_for('datahistori'))

# CRUD ADMIN
@app.route('/dataadmin')
def dataadmin():
    if 'user' in session:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users')
        data = cursor.fetchall()
        return render_template('dataadmin.html', users=data)
    else:
        # Jika belum login, arahkan ke halaman login
        return redirect(url_for('index'))
    
@app.route('/add_user', methods=['POST'])
def add_user():
    username = request.form['username']
    nomer_wa = request.form['nomer_wa']
    password = request.form['password']

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO users (username, nomer_wa, password) VALUES (%s, %s, %s)", 
                    (username, nomer_wa, hashed_password.decode('utf-8')))
    mysql.connection.commit()
    cursor.close()
    
    flash('User added successfully!', 'success')
    return redirect(url_for('dataadmin'))

@app.route('/update_user/<int:id>', methods=['POST'])
def update_user(id):
    username = request.form['username']
    nomer_wa = request.form['nomer_wa']
    password = request.form['password']

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    cursor = mysql.connection.cursor()
    cursor.execute("""
        UPDATE users 
        SET username=%s, nomer_wa=%s, password=%s 
        WHERE id=%s
    """, (username, nomer_wa, hashed_password.decode('utf-8'), id))
    mysql.connection.commit()
    cursor.close()
    
    flash('User updated successfully!', 'success')
    return redirect(url_for('dataadmin'))

@app.route('/delete_user/<int:id>')
def delete_user(id):
    cursor = mysql.connection.cursor()
    cursor.execute('DELETE FROM users WHERE id = %s', [id])
    mysql.connection.commit()
    cursor.close()
    
    flash('User deleted successfully!', 'success')
    return redirect(url_for('dataadmin'))

# CRUD SECURITY
@app.route('/datasecurity')
def datasecurity():
    if 'user' in session:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM security')
        data = cursor.fetchall()
        return render_template('datasecurity.html', security=data)
    else:
        return redirect(url_for('index'))

@app.route('/add', methods=['POST'])
def add_security():
    if request.method == 'POST':
        nama = request.form['nama']
        no_wa = request.form['no_wa']
        cursor = mysql.connection.cursor()
        cursor.execute('INSERT INTO security (nama, no_wa) VALUES (%s, %s)', (nama, no_wa))
        mysql.connection.commit()
        flash('Data added successfully!')
        return redirect(url_for('datasecurity'))

@app.route('/update/<int:id>', methods=['POST'])
def update_security(id):
    if request.method == 'POST':
        nama = request.form['nama']
        no_wa = request.form['no_wa']
        cursor = mysql.connection.cursor()
        cursor.execute('UPDATE security SET nama = %s, no_wa = %s WHERE id = %s', (nama, no_wa, id))
        mysql.connection.commit()
        flash('Data updated successfully!')
        return redirect(url_for('datasecurity'))

@app.route('/delete/<int:id>')
def delete_security(id):
    cursor = mysql.connection.cursor()
    cursor.execute('DELETE FROM security WHERE id = %s', (id,))
    mysql.connection.commit()
    flash('Data deleted successfully!')
    return redirect(url_for('datasecurity'))

if __name__ == '__main__':
    app.run(debug=True)