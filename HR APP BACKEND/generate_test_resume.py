from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os

def generate_resume(filename):
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "John Doe")
    
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 70, "Email: john.doe@example.com")
    c.drawString(50, height - 85, "Phone: +1-555-0199")
    c.drawString(50, height - 100, "Location: San Francisco, CA")
    
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 130, "Experience")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 150, "Senior Software Engineer | Tech Corp | 2020 - Present")
    c.setFont("Helvetica", 11)
    c.drawString(70, height - 165, "- Led a team of 5 engineers to build a scalable microservices architecture.")
    c.drawString(70, height - 180, "- Optimized database queries, reducing latency by 40%.")
    c.drawString(70, height - 195, "- Skills used: Python, FastAPI, PostgreSQL, AWS, Docker.")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 220, "Software Engineer | Startup Inc | 2018 - 2020")
    c.setFont("Helvetica", 11)
    c.drawString(70, height - 235, "- Developed a real-time analytics dashboard using React and Node.js.")
    c.drawString(70, height - 250, "- Implemented OAuth2 authentication and automated CI/CD pipelines.")
    c.drawString(70, height - 265, "- Skills used: JavaScript, React, Node.js, MongoDB, GitHub Actions.")
    
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 300, "Skills")
    c.setFont("Helvetica", 11)
    c.drawString(50, height - 320, "Python, FastAPI, SQL, PostgreSQL, Docker, Kubernetes, AWS, JavaScript, React, Node.js")
    
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 350, "Education")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 370, "B.S. Computer Science | University of Technology | 2014 - 2018")
    
    c.save()
    print(f"Generated {filename}")

if __name__ == "__main__":
    generate_resume("test_resume.pdf")
