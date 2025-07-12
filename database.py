# Add these imports at the top of your file
from datetime import datetime
import sqlite3

# Database setup function - call this once during app startup
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
