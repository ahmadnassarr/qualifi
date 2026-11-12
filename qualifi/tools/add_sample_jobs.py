"""Add sample Lebanese companies, each with one published job and a 12-question test.

Run on the server (or your computer) from the qualifi folder:
    python tools/add_sample_jobs.py you@gmail.com

Each company gets its own account on a "+" alias of that Gmail address
(you+cedarbank@gmail.com ...), so every company's emails arrive in your one inbox.
A random password is created for these accounts and printed once; change it from each
company's Account page. Safe to run twice: companies that already exist are skipped.

The company names are made up on purpose: a public site must not show job ads under
real businesses' names.
"""
import json
import os
import random
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from werkzeug.security import generate_password_hash  # noqa: E402

from qualifi import create_app  # noqa: E402
from qualifi.db import get_db  # noqa: E402

# Each question: (text, correct answer, [three wrong answers], topic)
COMPANIES = [
    {
        "alias": "cedarbank", "name": "Cedar Trust Bank", "location": "Achrafieh, Beirut",
        "about": "A Lebanese bank serving individuals and businesses with retail and corporate banking.",
        "job": dict(title="Junior Accountant", field="Accounting & Finance", level="junior", location="Achrafieh, Beirut",
                    employment_type="Full-time",
                    skills="Accounting, IFRS, Excel, Reconciliation, Financial Reporting, Arabic, English",
                    description="Join our Finance team at head office. You will record daily journal entries, prepare bank "
                                "and intercompany reconciliations, help with monthly closing and IFRS financial statements, "
                                "and support the external audit.\n\nRequirements: BS in Accounting or Finance, 1–2 years of "
                                "experience (fresh graduates with strong internships are welcome), solid Excel, good "
                                "knowledge of IFRS. Arabic and English required; French is a plus."),
        "questions": [
            ("Under IFRS, which statement shows a company’s assets, liabilities and equity at a point in time?",
             "Statement of financial position", ["Income statement", "Statement of cash flows", "Statement of changes in equity"], "Financial statements"),
            ("Which equation is always true in double-entry accounting?", "Assets = Liabilities + Equity",
             ["Assets = Revenue − Expenses", "Liabilities = Assets + Equity", "Equity = Assets + Liabilities"], "Accounting basics"),
            ("A bank reconciliation compares:", "The company’s cash records with the bank statement",
             ["Sales invoices with purchase orders", "The budget with actual results", "Payroll records with HR files"], "Reconciliation"),
            ("Which IFRS standard covers revenue from contracts with customers?", "IFRS 15", ["IFRS 9", "IFRS 16", "IAS 2"], "IFRS"),
            ("Which IFRS standard sets the rules for leases?", "IFRS 16", ["IFRS 15", "IAS 16", "IFRS 3"], "IFRS"),
            ("An increase in an expense account is recorded as a:", "Debit", ["Credit", "Either, depending on the amount", "Memo entry only"], "Accounting basics"),
            ("Depreciation spreads the cost of:", "A non-current asset over its useful life",
             ["Inventory over the financial year", "A bank loan over its term", "Revenue over several years"], "Fixed assets"),
            ("Accounts receivable represents:", "Money customers owe the company",
             ["Money the company owes suppliers", "Cash held at the bank", "Profits kept in the business"], "Accounting basics"),
            ("Which ratio measures short-term liquidity?", "Current ratio", ["Debt-to-equity ratio", "Return on equity", "Gross profit margin"], "Financial analysis"),
            ("Which Excel function finds a value in the first column of a range and returns a value from the same row?",
             "VLOOKUP", ["SUMIF", "CONCAT", "ROUND"], "Excel"),
            ("What is the standard VAT rate in Lebanon?", "11%", ["5%", "15%", "20%"], "Taxation"),
            ("An accrued expense is:", "An expense incurred but not yet paid at the reporting date",
             ["An expense paid in advance", "A bad debt written off", "A tax refund owed to the company"], "Accruals"),
        ],
    },
    {
        "alias": "beirutcare", "name": "Beirut Care Medical Center", "location": "Hamra, Beirut",
        "about": "A teaching hospital in Hamra offering medical, surgical and emergency care.",
        "job": dict(title="Registered Nurse, Medical-Surgical Unit", field="Nursing & Healthcare", level="junior",
                    location="Hamra, Beirut", employment_type="Full-time",
                    skills="Patient Care, Medication Administration, Vital Signs, BLS, Infection Control, IV Therapy, Electronic Health Records",
                    description="Provide safe, compassionate care to adult patients on a busy medical-surgical floor: "
                                "assessments, medication administration, IV therapy, wound care, patient education and "
                                "accurate documentation in the electronic health record.\n\nRequirements: BSN, valid Order of "
                                "Nurses in Lebanon license, current BLS certification, at least 1 year of acute-care "
                                "experience. Rotating shifts."),
        "questions": [
            ("What is the normal resting heart rate for an adult?", "60–100 beats per minute",
             ["40–60 beats per minute", "100–140 beats per minute", "20–40 beats per minute"], "Vital signs"),
            ("What is the single most effective way to prevent hospital-acquired infections?", "Hand hygiene",
             ["Wearing gloves at all times", "Giving every patient antibiotics", "Keeping the windows open"], "Infection control"),
            ("In adult CPR, chest compressions should be given at a rate of:", "100–120 per minute",
             ["60–80 per minute", "140–160 per minute", "30–50 per minute"], "BLS"),
            ("For an adult, chest compressions should be at least:", "5 cm (2 inches) deep",
             ["2 cm deep", "8–10 cm deep", "1 cm deep"], "BLS"),
            ("The compression-to-breath ratio for single-rescuer adult CPR is:", "30:2", ["15:1", "5:1", "30:5"], "BLS"),
            ("Before giving a medication, how many patient identifiers should you check?", "At least two",
             ["One is enough", "None if you know the patient", "Only the room number"], "Medication safety"),
            ("The ‘rights’ of medication administration include right patient, drug, dose, route and:", "Time",
             ["Room", "Colour", "Physician"], "Medication safety"),
            ("What is the normal respiratory rate for an adult at rest?", "12–20 breaths per minute",
             ["4–8 breaths per minute", "25–35 breaths per minute", "40–50 breaths per minute"], "Vital signs"),
            ("A stage 1 pressure injury is described as:", "Intact skin with non-blanchable redness",
             ["Full-thickness skin loss", "Exposed bone or tendon", "An open blister with a red wound bed"], "Wound care"),
            ("Used needles should be:", "Placed in a puncture-resistant sharps container right after use",
             ["Recapped and put in the regular bin", "Left on the tray for housekeeping", "Wrapped in a glove and discarded"], "Infection control"),
            ("An IV site is swollen, cool and pale. What should the nurse do first?", "Stop the infusion",
             ["Increase the flow rate", "Apply a warm compress and continue", "Flush the line forcefully"], "IV therapy"),
            ("What is a normal fasting blood glucose level in adults?", "70–99 mg/dL",
             ["40–60 mg/dL", "140–180 mg/dL", "200–250 mg/dL"], "Patient assessment"),
        ],
    },
    {
        "alias": "tarab", "name": "Tarab Music", "location": "Beirut (hybrid)",
        "about": "A Beirut-based music streaming app for Arabic and international listeners.",
        "job": dict(title="Product Designer (UI/UX)", field="Design", level="junior", location="Beirut (hybrid)",
                    employment_type="Full-time",
                    skills="Figma, UI Design, UX Design, Wireframing, Typography, Communication",
                    description="Design features used by millions of listeners: from user research and wireframes to "
                                "polished, accessible interfaces for iOS, Android and web. You will work closely with "
                                "product managers and engineers and contribute to our design system.\n\nRequirements: "
                                "a portfolio showing your process, strong Figma skills, understanding of accessibility "
                                "and mobile design patterns. Arabic is a plus."),
        "questions": [
            ("A wireframe is:", "A low-fidelity layout showing structure without final visuals",
             ["The final coded page", "The brand’s colour palette", "A logo sketch"], "Wireframing"),
            ("Under WCAG 2.1 AA, the minimum contrast ratio for normal body text is:", "4.5:1", ["2:1", "3:1", "7:1"], "Accessibility"),
            ("In Figma, a reusable element whose changes update all its instances is a:", "Component",
             ["Frame", "Group", "Mask"], "Figma"),
            ("Fitts’s law says the time to reach a target depends on:", "Its size and its distance",
             ["Its colour", "How many options are on screen", "The font used"], "UX principles"),
            ("Hick’s law says that decision time increases with:", "The number and complexity of choices",
             ["Screen brightness", "Button size", "Page load speed"], "UX principles"),
            ("Apple’s guidelines recommend a minimum touch target of:", "44 × 44 points",
             ["20 × 20 points", "12 × 12 points", "100 × 100 points"], "Mobile design"),
            ("Kerning is:", "The spacing between individual pairs of letters",
             ["The spacing between lines", "The weight of a font", "The colour of text"], "Typography"),
            ("A user persona is:", "A research-based profile of a typical target user",
             ["A real customer’s login", "The company style guide", "A usability test script"], "UX research"),
            ("Which format is best for icons that must stay sharp at any size?", "SVG", ["JPG", "GIF", "BMP"], "UI design"),
            ("An 8-point grid system means:", "Spacing and sizes are multiples of 8",
             ["Layouts always have 8 columns", "Only 8 colours are allowed", "Text is always 8 pt"], "UI design"),
            ("Testing with about five users usually reveals:", "Most of the major usability problems",
             ["Almost no problems", "Every possible bug", "Only visual issues"], "Usability testing"),
            ("Which is the most common primary navigation pattern in mobile music apps?", "A bottom tab bar",
             ["A right-click menu", "Footer text links", "A pop-up dialog on every screen"], "Mobile design"),
        ],
    },
    {
        "alias": "soukplaza", "name": "Souk Plaza Malls", "location": "Dbayeh, Metn",
        "about": "A group of shopping malls and department stores in Metn and Beirut.",
        "job": dict(title="Digital Marketing Specialist", field="Marketing & Sales", level="junior", location="Dbayeh, Metn",
                    employment_type="Full-time",
                    skills="Digital Marketing, Social Media, SEO, Google Analytics, Content Writing, Email Marketing",
                    description="Plan and run campaigns for our malls and department stores across social media, search "
                                "and email. You will manage the content calendar, run paid campaigns, track results in "
                                "Google Analytics and report on ROI.\n\nRequirements: 1–3 years in digital marketing, "
                                "hands-on Meta Ads and Google Ads experience, strong writing in English and Arabic, "
                                "comfort with data."),
        "questions": [
            ("SEO stands for:", "Search Engine Optimization", ["Social Engagement Online", "Sales Efficiency Output", "Search Email Outreach"], "SEO"),
            ("Click-through rate (CTR) is calculated as:", "Clicks ÷ impressions",
             ["Impressions ÷ clicks", "Conversions ÷ clicks", "Ad spend ÷ clicks"], "Metrics"),
            ("Google Analytics 4 organises data around:", "Events", ["Hits only", "Sessions only", "Pageviews only"], "Google Analytics"),
            ("CPC means:", "Cost per click", ["Clicks per campaign", "Customer purchase cost", "Cost per contact"], "Paid ads"),
            ("An A/B test:", "Compares two versions to see which performs better",
             ["Tests an ad in two countries", "Checks spelling in two languages", "Measures brand awareness"], "Optimisation"),
            ("Return on investment (ROI) is calculated as:", "(Gain − Cost) ÷ Cost",
             ["Cost ÷ Gain", "Gain × Cost", "Revenue − Clicks"], "Metrics"),
            ("A call to action is:", "A prompt that tells the user what to do next, such as “Shop now”",
             ["A phone call to a customer", "The company slogan", "A complaint from a customer"], "Content"),
            ("Organic social reach is:", "People reached without paid promotion",
             ["Reach from paid ads", "Reach from influencers only", "Email subscribers"], "Social media"),
            ("Customer lifetime value (CLV) is:", "The total revenue expected from a customer over the whole relationship",
             ["The value of a customer’s first purchase", "The cost of acquiring a customer", "A loyalty card balance"], "Metrics"),
            ("The 4 Ps of marketing are:", "Product, Price, Place, Promotion",
             ["People, Process, Profit, Planning", "Product, Profit, Packaging, Publicity", "Price, Partners, Press, Posts"], "Fundamentals"),
            ("Which metrics best show how engaging an email campaign was?", "Open rate and click rate",
             ["Number of followers", "Page load time", "Cost per click"], "Email marketing"),
            ("Retargeting shows ads to:", "People who already visited your website or app",
             ["Only new audiences", "Your own employees", "Random users in other countries"], "Paid ads"),
        ],
    },
    {
        "alias": "qadisha", "name": "Qadisha Engineering Consultants", "location": "Verdun, Beirut",
        "about": "An engineering and design consultancy working on buildings and infrastructure across the region.",
        "job": dict(title="Junior Civil / Structural Engineer", field="Engineering", level="fresh", location="Verdun, Beirut",
                    employment_type="Full-time",
                    skills="AutoCAD, Structural Analysis, Project Management, Teamwork, Excel, English",
                    description="Support senior engineers on the structural design of buildings and infrastructure "
                                "projects in the region: calculations, drawings, quantity take-offs and design reports.\n\n"
                                "Requirements: BE in Civil Engineering (fresh graduates welcome), Order of Engineers "
                                "registration or in progress, AutoCAD, familiarity with ETABS or SAFE is a plus, "
                                "good technical English."),
        "questions": [
            ("What is the SI unit of stress?", "Pascal (N/m²)", ["Newton", "Joule", "Watt"], "Mechanics"),
            ("Typical 28-day compressive strength of normal structural concrete is about:", "20–40 MPa",
             ["2–4 MPa", "200–400 MPa", "0.2–0.4 MPa"], "Concrete"),
            ("Concrete is:", "Strong in compression and weak in tension",
             ["Strong in tension and weak in compression", "Equally strong in both", "Weak in both"], "Concrete"),
            ("Steel bars are placed in a reinforced concrete beam mainly to resist:", "Tension",
             ["Compression", "Fire", "Corrosion"], "Reinforced concrete"),
            ("A simply supported beam of span L carries a uniform load w. The maximum bending moment is:", "wL²/8",
             ["wL/4", "wL²/2", "wL³/48"], "Structural analysis"),
            ("In AutoCAD, which command creates a parallel copy of a line at a set distance?", "OFFSET",
             ["MIRROR", "TRIM", "EXPLODE"], "AutoCAD"),
            ("The slump test measures:", "The workability of fresh concrete",
             ["The strength of hardened concrete", "The density of steel", "Soil bearing capacity"], "Concrete"),
            ("Increasing the water–cement ratio generally:", "Lowers the concrete’s strength",
             ["Raises the concrete’s strength", "Has no effect", "Makes concrete waterproof"], "Concrete"),
            ("A Gantt chart is used to:", "Schedule project tasks over time",
             ["Calculate beam deflection", "Design a mix of concrete", "Measure soil moisture"], "Project management"),
            ("Factor of safety is:", "Failure load ÷ allowable working load",
             ["Working load ÷ failure load", "Dead load + live load", "Span ÷ depth"], "Design"),
            ("The critical path in a project is:", "The longest chain of dependent tasks, which sets the minimum duration",
             ["The cheapest set of tasks", "The tasks done by the site manager", "The first task of the project"], "Project management"),
            ("Concrete is cured in order to:", "Keep it moist so the cement hydrates properly",
             ["Make it set faster in the sun", "Change its colour", "Remove the reinforcement"], "Concrete"),
        ],
    },
    {
        "alias": "levantmobile", "name": "Levant Mobile", "location": "Beirut",
        "about": "A mobile operator offering prepaid and postpaid lines, bundles and home internet.",
        "job": dict(title="Customer Care Agent", field="Customer Service", level="fresh", location="Beirut",
                    employment_type="Full-time",
                    skills="Customer Service, Communication, CRM, Arabic, English, French, Problem Solving",
                    description="Be the voice of Levant Mobile: help customers by phone, chat and in our shops with lines, bundles, "
                                "roaming, billing and technical questions, and log every case in our CRM.\n\n"
                                "Requirements: university degree or currently studying, excellent Arabic and English "
                                "(French is a plus), patience and clear communication, availability for shifts."),
        "questions": [
            ("A customer calls and is very angry. What should you do first?", "Listen fully and acknowledge their concern",
             ["Transfer them straight away", "Explain the company policy immediately", "Put them on hold to calm down"], "Handling complaints"),
            ("FCR stands for:", "First Contact Resolution", ["Final Customer Report", "Fast Call Response", "Full Credit Refund"], "Metrics"),
            ("CSAT measures:", "How satisfied customers are with an interaction",
             ["How long calls take", "How many calls are dropped", "The agent’s attendance"], "Metrics"),
            ("Net Promoter Score (NPS) asks customers:", "How likely they are to recommend the company, from 0 to 10",
             ["How long they waited", "Which agent helped them", "How much they spend monthly"], "Metrics"),
            ("Before discussing account details on the phone, you must:", "Verify the caller’s identity",
             ["Ask for their password", "Check their social media", "Offer a discount"], "Security"),
            ("A prepaid line is one where:", "The customer pays for credit before using it",
             ["The customer pays a bill at the end of the month", "Calls are always free", "Only data is included"], "Products"),
            ("If you can’t solve an issue during the call, you should:", "Set a clear expectation, escalate and follow up",
             ["Promise it will be fixed in minutes", "End the call politely", "Ask them to call back another day"], "Problem solving"),
            ("Average handle time (AHT) includes:", "Talk time, hold time and after-call work",
             ["Only the talk time", "Only the waiting time in the queue", "The time until the next call"], "Metrics"),
            ("Data roaming means:", "Using mobile data on another operator’s network while abroad",
             ["Using Wi-Fi at home", "Sharing data with another line", "Downloading large files"], "Products"),
            ("A CRM system is used to:", "Record and track every interaction with customers",
             ["Design marketing posters", "Pay employee salaries", "Repair phones"], "Tools"),
            ("Before putting a customer on hold, you should:", "Ask their permission and tell them how long it will take",
             ["Put them on hold without saying anything", "Leave them on hold until they hang up", "Transfer them instead"], "Call handling"),
            ("Which phrase uses positive language?", "“Here’s what I can do for you.”",
             ["“That’s not my department.”", "“There’s nothing I can do.”", "“You should have read the terms.”"], "Communication"),
        ],
    },
    {
        "alias": "rasbeirutacademy", "name": "Ras Beirut Academy", "location": "Ras Beirut",
        "about": "An independent, co-educational school following the Lebanese curriculum.",
        "job": dict(title="Mathematics Teacher (Grades 7–9)", field="Education", level="junior", location="Ras Beirut",
                    employment_type="Full-time",
                    skills="Communication, English, French, Leadership, Time Management, Teamwork",
                    description="Teach mathematics to intermediate classes following the Lebanese curriculum, prepare "
                                "students for the Brevet, plan engaging and differentiated lessons, and track progress "
                                "with formative assessment.\n\nRequirements: degree in Mathematics or Math Education, "
                                "teaching diploma is a plus, 1–3 years of classroom experience, excellent English "
                                "(French is a plus)."),
        "questions": [
            ("Solve: 3x + 7 = 22", "x = 5", ["x = 7", "x = 3", "x = 15"], "Algebra"),
            ("What is the slope of the line through (1, 2) and (3, 8)?", "3", ["2", "6", "1/3"], "Algebra"),
            ("What is the sum of the interior angles of a hexagon?", "720°", ["540°", "360°", "1080°"], "Geometry"),
            ("(x + 3)² equals:", "x² + 6x + 9", ["x² + 9", "x² + 3x + 9", "x² + 6x + 6"], "Algebra"),
            ("A right triangle has legs of 6 cm and 8 cm. Its hypotenuse is:", "10 cm", ["14 cm", "12 cm", "48 cm"], "Geometry"),
            ("What is the area of a circle with a radius of 5 cm?", "25π cm²", ["10π cm²", "5π cm²", "100π cm²"], "Geometry"),
            ("What is the mean of 4, 8, 6, 10 and 12?", "8", ["6", "10", "40"], "Statistics"),
            ("Two fair dice are rolled. The probability that the sum is 7 is:", "1/6", ["1/12", "1/36", "7/36"], "Probability"),
            ("Formative assessment is:", "Checking learning during a unit to guide teaching",
             ["The final exam of the year", "A national official exam", "An entrance test"], "Pedagogy"),
            ("In the revised Bloom’s taxonomy, the highest level of thinking is:", "Create",
             ["Remember", "Understand", "Apply"], "Pedagogy"),
            ("Differentiated instruction means:", "Adapting teaching to students’ different needs and levels",
             ["Giving every student the same worksheet", "Separating students by age", "Teaching only the top students"], "Pedagogy"),
            ("In Lebanon, the Brevet is the official exam taken at the end of:", "Grade 9",
             ["Grade 6", "Grade 12", "The first year of university"], "Lebanese curriculum"),
        ],
    },
    {
        "alias": "cornichegrand", "name": "Corniche Grand Hotel", "location": "Minet El Hosn, Beirut",
        "about": "A five-star hotel on the Beirut seafront.",
        "job": dict(title="Front Office Agent", field="Hospitality", level="fresh", location="Minet El Hosn, Beirut",
                    employment_type="Full-time",
                    skills="Customer Service, Communication, English, French, Arabic, Time Management, Teamwork",
                    description="Welcome our guests, handle check-in and check-out, reservations and requests, and make "
                                "every stay memorable. You will use our property management system and work closely with "
                                "housekeeping and concierge.\n\nRequirements: hospitality degree or diploma (fresh graduates "
                                "welcome), excellent English, French and Arabic, a warm and professional manner, "
                                "availability for rotating shifts."),
        "questions": [
            ("Check-in should begin with:", "Greeting the guest, then verifying the reservation and ID",
             ["Asking for payment immediately", "Handing over the room key", "Explaining the minibar prices"], "Front office"),
            ("Average Daily Rate (ADR) is:", "Room revenue ÷ rooms sold",
             ["Rooms sold ÷ rooms available", "Total revenue ÷ guests", "Rooms available ÷ staff"], "Revenue"),
            ("Occupancy rate is:", "Rooms sold ÷ rooms available",
             ["Room revenue ÷ rooms sold", "Guests ÷ beds", "Bookings ÷ cancellations"], "Revenue"),
            ("RevPAR stands for:", "Revenue per available room", ["Reservation per arrival", "Revenue per arriving resident", "Room evaluation per audit"], "Revenue"),
            ("A ‘no-show’ is a guest who:", "Has a reservation but neither arrives nor cancels",
             ["Arrives without a reservation", "Leaves without paying", "Checks out early"], "Reservations"),
            ("A ‘walk-in’ is a guest who:", "Arrives without a reservation",
             ["Walks to the hotel from the airport", "Has a confirmed booking", "Only uses the restaurant"], "Reservations"),
            ("Overbooking means:", "Accepting more reservations than there are rooms available",
             ["Booking a room for too many nights", "Charging a guest twice", "Booking a suite for one guest"], "Reservations"),
            ("In a hotel, PMS stands for:", "Property Management System",
             ["Personal Messaging Service", "Payment Monitoring Software", "Premium Member Status"], "Systems"),
            ("Upselling at the front desk means:", "Offering a better room category or extra services",
             ["Selling the hotel to investors", "Raising the price without telling the guest", "Asking for a tip"], "Sales"),
            ("A guest complains that their room is noisy. You should:", "Apologise and promptly offer a solution, such as a room move",
             ["Tell them all rooms are noisy", "Ask them to complain in writing tomorrow", "Ignore it if the hotel is full"], "Guest relations"),
            ("Guests’ credit card details should be:", "Handled securely and never written down or shared",
             ["Written on the registration card", "Emailed to the accounts team", "Kept in a notebook at the desk"], "Security"),
            ("A late check-out is:", "Leaving after the standard check-out time, usually with approval",
             ["Arriving after midnight", "Paying the bill a day later", "Checking out before breakfast"], "Front office"),
        ],
    },
    {
        "alias": "sannine", "name": "Sannine Insurance Group", "location": "Verdun, Beirut",
        "about": "A Lebanese insurance company offering health, motor and life cover.",
        "job": dict(title="HR Officer, Talent Acquisition", field="Human Resources", level="junior", location="Verdun, Beirut",
                    employment_type="Full-time",
                    skills="Communication, Excel, Payroll, Teamwork, Time Management, English, Arabic, French",
                    description="Own the hiring process for branches and head office: write job descriptions, screen "
                                "candidates, run structured interviews, coordinate offers and onboarding, and keep HR "
                                "records accurate.\n\nRequirements: degree in Human Resources, Business or Psychology, "
                                "1–3 years in HR or recruitment, good knowledge of Lebanese labour law and NSSF "
                                "procedures, Arabic, English and French."),
        "questions": [
            ("The main purpose of a job description is to:", "Define the duties, responsibilities and requirements of a role",
             ["Set the employee’s yearly bonus", "Replace the employment contract", "Advertise the company’s products"], "Recruitment"),
            ("A structured interview is one where:", "All candidates are asked the same questions and scored the same way",
             ["Each interviewer asks whatever they like", "Only the CV is discussed", "The candidate chooses the questions"], "Interviewing"),
            ("The STAR method stands for:", "Situation, Task, Action, Result",
             ["Skills, Training, Attitude, Results", "Strengths, Talents, Abilities, Roles", "Start, Test, Assess, Recruit"], "Interviewing"),
            ("Onboarding is:", "The process of welcoming and integrating new employees",
             ["Posting a job on a website", "Firing an employee", "Calculating salaries"], "Onboarding"),
            ("Lebanon’s national social security fund is known as:", "NSSF (CNSS)", ["IMF", "OMSAR", "CDR"], "Lebanese labour law"),
            ("Under the Lebanese Labour Law, the maximum probation period is:", "3 months", ["1 month", "6 months", "12 months"], "Lebanese labour law"),
            ("Employee turnover rate is calculated as:", "Leavers ÷ average number of employees × 100",
             ["New hires ÷ leavers", "Salaries ÷ employees", "Vacancies ÷ applicants"], "HR metrics"),
            ("KPI stands for:", "Key Performance Indicator", ["Key Personnel Index", "Knowledge Process Input", "Known Pay Increase"], "Performance"),
            ("The halo effect in interviews is:", "Letting one strong trait shape your whole judgment of a candidate",
             ["Interviewing in a bright room", "Asking candidates about their hobbies", "Hiring the first candidate seen"], "Bias"),
            ("The main purpose of an exit interview is to:", "Understand why employees leave",
             ["Convince the employee to stay at any cost", "Check the final salary", "Collect the office keys"], "Retention"),
            ("Which interview question is inappropriate and risky to ask?", "“Are you planning to have children?”",
             ["“Tell me about a project you led.”", "“Why do you want this role?”", "“How do you handle tight deadlines?”"], "Interviewing"),
            ("Net salary is:", "Gross salary minus deductions such as income tax and social security",
             ["Gross salary plus bonuses", "The salary before any deductions", "The employer’s total cost"], "Payroll"),
        ],
    },
]



def main():
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        sys.exit("Usage: python tools/add_sample_jobs.py you@gmail.com")
    local, domain = sys.argv[1].strip().lower().split("@", 1)
    password = "Q-" + secrets.token_urlsafe(12)
    password_hash = generate_password_hash(password)
    rng = random.Random(2026)
    app = create_app()
    added = 0
    with app.app_context():
        db = get_db()
        for co in COMPANIES:
            email = f"{local}+{co['alias']}@{domain}"
            if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                print("already there:", co["name"])
                continue
            uid = db.execute("INSERT INTO users (email, password_hash, role, name) VALUES (?, ?, 'company', ?)",
                             (email, password_hash, f"{co['name']} HR")).lastrowid
            db.execute("INSERT INTO companies (user_id, company_name, location, about) VALUES (?, ?, ?, ?)",
                       (uid, co["name"], co["location"], co["about"]))
            j = co["job"]
            job_id = db.execute(
                "INSERT INTO jobs (company_id, title, field, level, location, employment_type, description, skills, status, "
                "pass_mark, questions_per_test, time_limit_min, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', 6, 10, 15, strftime('%Y-%m-%dT%H:%M:%S', 'now'))",
                (uid, j["title"], j["field"], j["level"], j["location"], j["employment_type"], j["description"], j["skills"])
            ).lastrowid
            for text, correct, wrong, topic in co["questions"]:
                options = [correct] + wrong
                rng.shuffle(options)
                db.execute("INSERT INTO questions (job_id, text, options_json, answer_index, source_doc, topic, origin) "
                           "VALUES (?, ?, ?, ?, ?, ?, 'manual')",
                           (job_id, text, json.dumps(options), options.index(correct), f"{co['name']} question bank", topic))
            added += 1
            print(f"added {co['name']:<30} {email:<44} {j['title']}")
        db.commit()
    if added:
        print(f"\nPassword for the new company accounts (shown only now, write it down):\n\n    {password}\n")


if __name__ == "__main__":
    main()
