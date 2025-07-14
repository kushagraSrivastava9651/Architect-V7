# Add these imports at the top of your existing file
import sqlite3
from datetime import datetime

# Add these database functions
def init_database():
    """Initialize the database with required tables"""
    conn = sqlite3.connect('dxf_analysis.db')
    cursor = conn.cursor()
    
    # Create form_submissions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS form_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            file_name TEXT NOT NULL,
            room_count INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create room_submissions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS room_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form_submission_id INTEGER,
            unit_name TEXT NOT NULL,
            room_name TEXT NOT NULL,
            width_feet INTEGER NOT NULL,
            width_inches INTEGER NOT NULL,
            height_feet INTEGER NOT NULL,
            height_inches INTEGER NOT NULL,
            FOREIGN KEY (form_submission_id) REFERENCES form_submissions (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    
def feet_inches_to_mm(feet: int, inches: int) -> float:
    return round((feet * 12 + inches) * 25.4, 2)

def store_form_data(user_name, file_name, room_count, submitted_rooms):
    """Store form data in the database"""
    conn = sqlite3.connect('dxf_analysis.db')
    cursor = conn.cursor()
    
    try:
        # Store form submission
        cursor.execute('''
            INSERT INTO form_submissions (user_name, file_name, room_count)
            VALUES (?, ?, ?)
        ''', (user_name, file_name, room_count))
        
        form_submission_id = cursor.lastrowid
        
        # Store room data
        for room in submitted_rooms:
            cursor.execute('''
                INSERT INTO room_submissions 
                (form_submission_id, unit_name, room_name, width_feet, width_inches, height_feet, height_inches)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                form_submission_id,
                room['block_name'],  # unit_name
                room['name'],        # room_name
                room['width_feet'],
                room['width_inches'],
                room['height_feet'],
                room['height_inches']
            ))
        
        conn.commit()
        return form_submission_id
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_all_form_submissions():
    """Get all form submissions from database"""
    conn = sqlite3.connect('dxf_analysis.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_name, file_name, room_count, created_at
        FROM form_submissions
        ORDER BY created_at DESC
    ''')
    
    submissions = cursor.fetchall()
    conn.close()
    
    return [
        {
            'id': row[0],
            'user_name': row[1],
            'file_name': row[2],
            'room_count': row[3],
            'created_at': row[4]
        }
        for row in submissions
    ]

def get_form_data_by_id(form_id):
    """Get form data and rooms by form ID"""
    conn = sqlite3.connect('dxf_analysis.db')
    cursor = conn.cursor()
    
    # Get form submission
    cursor.execute('''
        SELECT user_name, file_name, room_count, created_at
        FROM form_submissions
        WHERE id = ?
    ''', (form_id,))
    
    form_data = cursor.fetchone()
    if not form_data:
        conn.close()
        return None
    
    # Get rooms
    cursor.execute('''
        SELECT unit_name, room_name, width_feet, width_inches, height_feet, height_inches
        FROM room_submissions
        WHERE form_submission_id = ?
    ''', (form_id,))
    
    rooms = cursor.fetchall()
    conn.close()
    
    return {
        'form': {
            'user_name': form_data[0],
            'file_name': form_data[1],
            'room_count': form_data[2],
            'created_at': form_data[3]
        },
        'rooms': [
            {
                'unit_name': room[0],
                'room_name': room[1],
                'width_feet': room[2],
                'width_inches': room[3],
                'height_feet': room[4],
                'height_inches': room[5],
                'width_mm': feet_inches_to_mm(room[2], room[3]),
                'height_mm': feet_inches_to_mm(room[4], room[5])
            }
            for room in rooms
        ]
    }