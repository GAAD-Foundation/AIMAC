-- =============================================================================
-- File: AIMAC_DATA_DIR/schema/005_categories.sql
-- =============================================================================

-- This file defines the schema for the 'categories' table and seeds it
-- with the 29 standard AIMAC categories. Each category includes a complete
-- user prompt for generating web pages in that category.
-- Categories from https://webaim.org/projects/million/#categories

-- IMMUTABILITY NOTICE
-- The enabled category set used for collection is immutable and fixed at 28.
-- Do not change the `enabled` flags. Cache logic and leaderboards assume
-- a fixed set of enabled categories for all time.

-- NOTE: To prevent overfitting/gaming, prompts are randomized at runtime using
-- fragments from the prompt_fragments column. See prompt_randomizer.py for the
-- randomization logic that replaces "similar to" lists with random selections.

-- =============================================================================
-- TABLE DEFINITION
-- =============================================================================

CREATE TABLE IF NOT EXISTS "categories" (
    "pk"                INTEGER PRIMARY KEY AUTOINCREMENT, -- primary key
    "category_slug"     TEXT    NOT NULL, -- e.g. "arts-and-entertainment"
    "name"              TEXT    NOT NULL, -- e.g. "Arts and Entertainment"
    "description"       TEXT, -- e.g. "Music, movies, visual arts, performing arts, and entertainment industry news and resources."
    "user_prompt"       TEXT, -- Complete prompt for generating web pages in this category
    "prompt_fragments"  TEXT, -- JSON: interchangeable text pieces for prompt randomization (nullable)
    "enabled"           BOOLEAN NOT NULL DEFAULT 0,
    "created_at" DATETIME DEFAULT (CURRENT_TIMESTAMP)
    -- Note: No updated_at column. This is seed data that doesn't change at runtime.
    -- Prompt rotations are tracked via git history, not database timestamps.
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Ensure each category_slug is unique so it can be referenced by FK
CREATE UNIQUE INDEX IF NOT EXISTS "idx_categories_slug"
    ON "categories" ("category_slug");

-- =============================================================================
-- TRIGGERS (immutability guards)
-- =============================================================================

-- Prevent changing the `enabled` flag; the enabled set is immutable (28)
CREATE TRIGGER IF NOT EXISTS trg_categories_enabled_immutable
BEFORE UPDATE OF enabled ON "categories"
FOR EACH ROW
WHEN NEW.enabled IS NOT OLD.enabled
BEGIN
    SELECT RAISE(ABORT, 'categories.enabled is immutable in AIMAC');
END;

-- =============================================================================
-- DATA SEEDING
-- =============================================================================

-- Bulk insert all 29 AIMAC categories with their complete user prompts.
INSERT OR IGNORE INTO "categories" (
    "category_slug", "name", "description", "enabled", "user_prompt", "prompt_fragments"
) VALUES
    -- Adult Content Category, disabled
    ('adult-content',
     'Adult Content',
     'Websites intended for mature audiences with age verification and privacy considerations.',
     0,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Adult Content" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Adult Content"
- Description: Websites intended for mature audiences with age verification and privacy considerations.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Adult Content" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Resources", "Support", "Contact".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Adult Content" category. Consider themes similar to: "Wellness", "Education", "Support Resources".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "privacy", "consent", "wellness".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Learn More", "Get Support", "Read Guidelines".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Adult Content" sector. Ideas similar but not limited to: "anonymous Q&A", "resource finder".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "privacy tips", "educational links", "support hotlines".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     NULL),  -- disabled category, no fragments needed

    -- Arts and Entertainment Category
    ('arts-and-entertainment',
     'Arts and Entertainment',
     'Music, movies, visual arts, performing arts, and entertainment industry news and resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Arts and Entertainment" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Arts and Entertainment"
- Description: Music, movies, visual arts, performing arts, and entertainment industry news and resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Arts and Entertainment" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Events", "Artists", "Reviews".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Arts and Entertainment" category. Consider themes similar to: "Artist Spotlights", "Venue Guide", "Industry News".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "residency", "critique", "ensemble".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Buy Tickets", "Read Reviews", "Follow Artist".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Arts and Entertainment" sector. Ideas similar but not limited to: "event calendar".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "critic picks", "behind the scenes", "this week''s shows".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Events", "Artists", "Reviews", "Galleries", "Tickets", "Schedule", "News", "About", "Contact", "Shop", "Subscribe", "Community"], "section_themes": ["Artist Spotlights", "Venue Guide", "Industry News", "Behind the Scenes", "Upcoming Shows", "Creative Process", "Cultural Impact", "Emerging Talent", "Award Winners", "Retrospectives"], "terminology": ["residency", "critique", "ensemble", "performance", "premiere", "installation", "repertoire", "collaboration", "exhibition", "commission", "staging", "curation"], "ctas": ["Buy Tickets", "Read Reviews", "Follow Artist", "Watch Preview", "View Gallery", "Book Now", "Join Waitlist", "Get Passes", "Subscribe", "Explore", "Discover", "Connect"], "engagement": ["event calendar", "ticket finder", "artist directory", "venue map", "show planner", "review aggregator"], "sidebar": ["critic picks", "behind the scenes", "this week''s shows", "artist interviews", "venue spotlights", "trending now", "editor''s choice", "fan favorites", "upcoming premieres"]}'),

    -- Automotive Category
    ('automotive',
     'Automotive',
     'Automotive news, car reviews, repair tips, and dealership resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Automotive" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Automotive"
- Description: Automotive news, car reviews, repair tips, and dealership resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Automotive" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Inventory", "Service", "Financing".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Automotive" category. Consider themes similar to: "Certified Pre-Owned", "Service Center", "Parts Department".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "MSRP", "warranty coverage", "service interval".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Schedule Test Drive", "Book Service", "Request Financing".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Automotive" sector. Ideas similar but not limited to: "trade-in calculator".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "customer reviews", "maintenance reminders", "featured inventory".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Inventory", "Service", "Financing", "Trade-In", "Parts", "About", "Contact", "Specials", "Reviews", "Schedule", "Careers", "Blog"], "section_themes": ["Certified Pre-Owned", "Service Center", "Parts Department", "New Arrivals", "Featured Vehicles", "Financing Options", "Trade-In Value", "Customer Stories", "Service Specials", "Maintenance Tips"], "terminology": ["MSRP", "warranty coverage", "service interval", "certified pre-owned", "trade-in value", "APR financing", "lease terms", "mileage rating", "safety features", "fuel efficiency", "torque", "horsepower"], "ctas": ["Schedule Test Drive", "Book Service", "Request Financing", "Get Quote", "View Inventory", "Calculate Payment", "Check Availability", "Apply Online", "Contact Dealer", "Compare Models", "Trade In", "Get Pre-Approved"], "engagement": ["trade-in calculator", "payment estimator", "vehicle comparison", "service scheduler", "financing calculator", "inventory search"], "sidebar": ["customer reviews", "maintenance reminders", "featured inventory", "service specials", "new arrivals", "price drops", "certified selection", "dealer awards", "financing offers"]}'),

    -- Business Category
    ('business',
     'Business',
     'Business news, corporate resources, finance, and professional advice.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Business" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Business"
- Description: Business news, corporate resources, finance, and professional advice.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Business" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Services", "Case Studies", "Blog".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Business" category. Consider themes similar to: "Consulting Services", "Industry Insights", "Client Success".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "scalability", "ROI optimization", "stakeholder alignment".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Schedule Consultation", "Download Whitepaper", "Request Proposal".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Business" sector. Ideas similar but not limited to: "ROI calculator".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "market insights", "client success stories", "industry trends".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Services", "Case Studies", "Blog", "About", "Pricing", "Resources", "Partners", "Careers", "Contact", "FAQ", "Testimonials", "Portfolio"], "section_themes": ["Consulting Services", "Industry Insights", "Client Success", "Market Analysis", "Strategic Advisory", "Growth Stories", "Expert Perspectives", "Business Solutions", "Leadership Insights", "Innovation Hub"], "terminology": ["scalability", "ROI optimization", "stakeholder alignment", "value proposition", "market positioning", "competitive advantage", "operational efficiency", "strategic planning", "digital transformation", "performance metrics", "business intelligence", "process optimization"], "ctas": ["Schedule Consultation", "Download Whitepaper", "Request Proposal", "Get Started", "Learn More", "Contact Us", "Book Demo", "Request Quote", "Start Free Trial", "Talk to Expert", "See Pricing", "View Case Study"], "engagement": ["ROI calculator", "assessment quiz", "savings estimator", "comparison tool", "cost analyzer", "benchmark checker"], "sidebar": ["market insights", "client success stories", "industry trends", "expert tips", "weekly updates", "featured resources", "upcoming webinars", "latest research", "partner spotlights"]}'),

    -- Careers Category
    ('careers',
     'Careers',
     'Job boards, career advice, resume tips, and professional resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Careers" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Careers"
- Description: Job boards, career advice, resume tips, and professional resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Careers" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Job Search", "Resume Builder", "Interview Prep".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Careers" category. Consider themes similar to: "Current Openings", "Career Development", "Professional Networking".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "key competencies", "career trajectory", "skill assessment".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Apply Today", "Build Resume", "Schedule Interview".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Careers" sector. Ideas similar but not limited to: "salary comparison".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "featured positions", "career advice", "industry salary data".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Job Search", "Resume Builder", "Interview Prep", "Companies", "Salary Info", "Resources", "About", "Blog", "Contact", "Career Advice", "Skills", "Networking"], "section_themes": ["Current Openings", "Career Development", "Professional Networking", "Industry Trends", "Skill Building", "Success Stories", "Salary Insights", "Interview Tips", "Resume Guide", "Job Market Analysis"], "terminology": ["key competencies", "career trajectory", "skill assessment", "professional development", "job market", "transferable skills", "career pivot", "networking", "personal branding", "applicant tracking", "cover letter", "references"], "ctas": ["Apply Today", "Build Resume", "Schedule Interview", "Search Jobs", "Get Alerts", "Upload Resume", "Create Profile", "Connect Now", "Explore Careers", "Find Companies", "Set Preferences", "Start Application"], "engagement": ["salary comparison", "skills assessment", "career path finder", "resume analyzer", "interview simulator", "job match quiz"], "sidebar": ["featured positions", "career advice", "industry salary data", "hiring trends", "success stories", "skill courses", "top employers", "recent posts", "popular searches"]}'),

    -- Education Category
    ('education',
     'Education',
     'Educational resources, school and university information, and online learning platforms.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Education" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Education"
- Description: Educational resources, school and university information, and online learning platforms.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Education" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Programs", "Admissions", "Student Portal".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Education" category. Consider themes similar to: "Degree Programs", "Course Catalog", "Campus Life".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "prerequisites", "core curriculum", "graduation requirements".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Apply Today", "Schedule Tour", "Request Information".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Education" sector. Ideas similar but not limited to: "program finder".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "upcoming deadlines", "student success stories", "campus news".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Programs", "Admissions", "Student Portal", "Faculty", "Research", "Campus Life", "Alumni", "About", "Apply", "Contact", "Events", "Library"], "section_themes": ["Degree Programs", "Course Catalog", "Campus Life", "Student Success", "Research Excellence", "Faculty Spotlight", "Alumni Network", "Academic Resources", "Enrollment Info", "Financial Aid"], "terminology": ["prerequisites", "core curriculum", "graduation requirements", "accreditation", "credit hours", "academic calendar", "enrollment", "financial aid", "scholarship", "thesis", "dissertation", "syllabus"], "ctas": ["Apply Today", "Schedule Tour", "Request Information", "Start Application", "Explore Programs", "Visit Campus", "Meet Faculty", "Calculate Aid", "Register Now", "Contact Advisor", "View Courses", "Download Catalog"], "engagement": ["program finder", "tuition calculator", "course planner", "campus tour scheduler", "advisor chat", "application tracker"], "sidebar": ["upcoming deadlines", "student success stories", "campus news", "events calendar", "faculty highlights", "research updates", "scholarship opportunities", "alumni achievements", "application tips"]}'),

    -- Family and Parenting Category
    ('family-and-parenting',
     'Family and Parenting',
     'Parenting advice, family resources, childcare tips, and support for parents.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Family and Parenting" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Family and Parenting"
- Description: Parenting advice, family resources, childcare tips, and support for parents.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Family and Parenting" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Parenting Guide", "Child Development", "Support Groups".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Family and Parenting" category. Consider themes similar to: "Age-by-Age Guide", "Family Wellness", "Parenting Tips".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "developmental milestones", "sleep training", "behavior management".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Get Parenting Tips", "Join Support Group", "Connect with Experts".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Family and Parenting" sector. Ideas similar but not limited to: "milestone tracker".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "weekly tips", "parent success stories", "expert advice".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Parenting Guide", "Child Development", "Support Groups", "Activities", "Health", "Education", "Resources", "Community", "Blog", "About", "Contact", "Shop"], "section_themes": ["Age-by-Age Guide", "Family Wellness", "Parenting Tips", "Child Safety", "Educational Activities", "Healthy Habits", "Special Needs", "Family Fun", "Parenting Challenges", "Expert Advice"], "terminology": ["developmental milestones", "sleep training", "behavior management", "positive reinforcement", "attachment parenting", "screen time", "nutrition", "social skills", "emotional intelligence", "discipline strategies", "self-care", "family bonding"], "ctas": ["Get Parenting Tips", "Join Support Group", "Connect with Experts", "Find Activities", "Subscribe", "Read Guide", "Ask Question", "Share Story", "Download Resource", "Book Session", "Start Free", "Get Help"], "engagement": ["milestone tracker", "activity finder", "sleep schedule planner", "meal planner", "behavior log", "development quiz"], "sidebar": ["weekly tips", "parent success stories", "expert advice", "age-specific guides", "community highlights", "popular questions", "upcoming events", "resource library", "featured products"]}'),

    -- Food and Drink Category
    ('food-and-drink',
     'Food and Drink',
     'Recipes, restaurant guides, cooking tips, and nutrition resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Food and Drink" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Food and Drink"
- Description: Recipes, restaurant guides, cooking tips, and nutrition resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Food and Drink" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Recipes", "Restaurant Reviews", "Cooking Classes".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Food and Drink" category. Consider themes similar to: "Chef''s Recipes", "Wine Pairings", "Cooking Tips".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "mise en place", "reduction", "braising".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Try Recipe", "Reserve Table", "Join Cooking Class".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Food and Drink" sector. Ideas similar but not limited to: "wine pairing finder".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "daily specials", "chef interviews", "seasonal ingredients".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Recipes", "Restaurant Reviews", "Cooking Classes", "Wine", "Meal Plans", "Shop", "About", "Blog", "Contact", "Events", "Catering", "Reservations"], "section_themes": ["Chef''s Recipes", "Wine Pairings", "Cooking Tips", "Restaurant Guide", "Seasonal Menus", "Technique Tutorials", "Ingredient Spotlight", "Kitchen Essentials", "Culinary Trends", "Food Culture"], "terminology": ["mise en place", "reduction", "braising", "sautéing", "emulsification", "fermentation", "plating", "seasoning", "umami", "terroir", "sommelier", "gastronomy"], "ctas": ["Try Recipe", "Reserve Table", "Join Cooking Class", "Order Now", "View Menu", "Book Event", "Subscribe", "Download Cookbook", "Watch Tutorial", "Make Reservation", "Get Delivered", "Start Order"], "engagement": ["wine pairing finder", "recipe calculator", "meal planner", "ingredient substitution tool", "cooking timer", "nutrition calculator"], "sidebar": ["daily specials", "chef interviews", "seasonal ingredients", "trending recipes", "restaurant picks", "wine selections", "cooking tips", "featured chefs", "food news"]}'),

    -- Gambling/Casinos Category
    ('gambling-casinos',
     'Gambling/Casinos',
     'Gambling news, casino guides, betting tips, and gaming resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Gambling/Casinos" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Gambling/Casinos"
- Description: Gambling news, casino guides, betting tips, and gaming resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Gambling/Casinos" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Casino Finder", "Game Guide", "Responsible Play".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Gambling/Casinos" category. Consider themes similar to: "Table Games", "Poker Room", "Sports Betting".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "blackjack strategy", "progressive jackpot", "bankroll management".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Play Now", "Learn Strategy", "Set Limits".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Gambling/Casinos" sector. Ideas similar but not limited to: "odds calculator".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "jackpot winners", "casino reviews", "responsible gaming tips".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Casino Finder", "Game Guide", "Responsible Play", "Promotions", "Reviews", "News", "About", "Support", "Contact", "VIP", "Events", "Help"], "section_themes": ["Table Games", "Poker Room", "Sports Betting", "Slots Guide", "Tournament Schedule", "Strategy Tips", "Casino Reviews", "Betting Basics", "Jackpot Winners", "Game Rules"], "terminology": ["blackjack strategy", "progressive jackpot", "bankroll management", "house edge", "payout percentage", "wagering requirements", "comp points", "betting limits", "variance", "expected value", "odds", "stake"], "ctas": ["Play Now", "Learn Strategy", "Set Limits", "Claim Bonus", "Join Tournament", "View Odds", "Find Casino", "Get Started", "Read Rules", "Contact Support", "Sign Up", "Redeem Offer"], "engagement": ["odds calculator", "bankroll tracker", "strategy simulator", "casino comparison", "bonus finder", "game finder"], "sidebar": ["jackpot winners", "casino reviews", "responsible gaming tips", "tournament schedule", "bonus offers", "strategy guides", "game tips", "latest promotions", "news updates"]}'),

    -- Gaming Category
    ('gaming',
     'Gaming',
     'Video games, esports news, game reviews, and online gaming communities.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Gaming" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Gaming"
- Description: Video games, esports news, game reviews, and online gaming communities.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Gaming" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Game Library", "Esports", "Tournaments".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Gaming" category. Consider themes similar to: "New Releases", "Game Reviews", "Player Profiles".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "meta strategy", "skill-based matchmaking", "achievements".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Download Now", "Watch Tournament", "Join Clan".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Gaming" sector. Ideas similar but not limited to: "achievement tracker".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "patch notes", "pro player highlights", "gaming news".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Game Library", "Esports", "Tournaments", "Reviews", "News", "Community", "Shop", "Support", "About", "Streaming", "Forums", "Wiki"], "section_themes": ["New Releases", "Game Reviews", "Player Profiles", "Tournament Coverage", "Strategy Guides", "Esports News", "Indie Spotlight", "Gaming Hardware", "Community Highlights", "Patch Notes"], "terminology": ["meta strategy", "skill-based matchmaking", "achievements", "DLC", "framerate", "latency", "competitive ranking", "season pass", "cross-platform", "speedrun", "build guide", "tier list"], "ctas": ["Download Now", "Watch Tournament", "Join Clan", "Play Free", "Pre-Order", "Watch Stream", "Join Discord", "Read Review", "View Leaderboard", "Enter Contest", "Subscribe", "Start Playing"], "engagement": ["achievement tracker", "loadout builder", "clan finder", "match history", "stats comparison", "tournament bracket"], "sidebar": ["patch notes", "pro player highlights", "gaming news", "stream schedule", "tournament results", "community clips", "trending games", "editor picks", "release calendar"]}'),

    -- Government Category
    ('government',
     'Government',
     'Government agencies, official portals, public services, and regulatory resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Government" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Government"
- Description: Government agencies, official portals, public services, and regulatory resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Government" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Services", "Departments", "Public Records".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Government" category. Consider themes similar to: "Government Services", "Public Safety", "Business Licenses".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "FOIA request", "public records", "permit processing".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Apply for Permit", "Access Records", "Report Issue".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Government" sector. Ideas similar but not limited to: "service finder".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "public announcements", "meeting schedules", "service updates".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Services", "Departments", "Public Records", "Permits", "News", "Contact", "About", "Events", "Jobs", "FAQs", "Forms", "Transparency"], "section_themes": ["Government Services", "Public Safety", "Business Licenses", "Community Programs", "Civic Engagement", "Public Works", "Emergency Services", "Planning & Zoning", "Budget & Finance", "Elected Officials"], "terminology": ["FOIA request", "public records", "permit processing", "ordinance", "municipal code", "public hearing", "zoning variance", "fiscal year", "compliance", "procurement", "constituent services", "transparency"], "ctas": ["Apply for Permit", "Access Records", "Report Issue", "Pay Online", "Submit Request", "Find Services", "Contact Department", "File Complaint", "Register", "Download Form", "Check Status", "Schedule Appointment"], "engagement": ["service finder", "permit tracker", "meeting calendar", "issue reporter", "document search", "payment portal"], "sidebar": ["public announcements", "meeting schedules", "service updates", "emergency alerts", "community events", "recent ordinances", "job openings", "press releases", "budget reports"]}'),

    -- Health and Fitness Category
    ('health-and-fitness',
     'Health and Fitness',
     'Healthcare, wellness, fitness tips, nutrition, and medical resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Health and Fitness" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Health and Fitness"
- Description: Healthcare, wellness, fitness tips, nutrition, and medical resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Health and Fitness" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Find Provider", "Wellness Center", "Fitness Classes".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Health and Fitness" category. Consider themes similar to: "Medical Services", "Fitness Programs", "Nutrition Counseling".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "preventive screening", "personal training", "holistic wellness".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Schedule Appointment", "Book Class", "Join Program".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Health and Fitness" sector. Ideas similar but not limited to: "health tracker".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "wellness tips", "success stories", "health news".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Find Provider", "Wellness Center", "Fitness Classes", "Nutrition", "Mental Health", "Insurance", "About", "Contact", "Blog", "Appointments", "Pharmacy", "Lab Results"], "section_themes": ["Medical Services", "Fitness Programs", "Nutrition Counseling", "Mental Wellness", "Preventive Care", "Specialty Services", "Patient Resources", "Wellness Tips", "Health Education", "Recovery Programs"], "terminology": ["preventive screening", "personal training", "holistic wellness", "BMI", "metabolic rate", "rehabilitation", "chronic care", "telehealth", "wellness plan", "health assessment", "vital signs", "lifestyle modification"], "ctas": ["Schedule Appointment", "Book Class", "Join Program", "Find Doctor", "Get Started", "View Schedule", "Calculate BMI", "Contact Us", "Sign Up", "Request Consultation", "Start Trial", "Learn More"], "engagement": ["health tracker", "workout planner", "calorie calculator", "appointment scheduler", "symptom checker", "fitness assessment"], "sidebar": ["wellness tips", "success stories", "health news", "class schedule", "nutrition advice", "provider spotlights", "patient testimonials", "health alerts", "fitness challenges"]}'),

    -- Hobbies and Interests Category
    ('hobbies-and-interests',
     'Hobbies and Interests',
     'Hobbies, crafts, DIY projects, collecting, and special interest communities.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Hobbies and Interests" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Hobbies and Interests"
- Description: Hobbies, crafts, DIY projects, collecting, and special interest communities.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Hobbies and Interests" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Craft Tutorials", "Community", "Events".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Hobbies and Interests" category. Consider themes similar to: "DIY Tutorials", "Local Clubs", "Online Communities".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "crafting technique", "material sourcing", "skill progression".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Try Tutorial", "Join Community", "Share Project".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Hobbies and Interests" sector. Ideas similar but not limited to: "project inspiration board".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "featured makers", "upcoming workshops", "craft trends".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Craft Tutorials", "Community", "Events", "Shop", "Gallery", "Blog", "About", "Contact", "Forums", "Classes", "Resources", "Projects"], "section_themes": ["DIY Tutorials", "Local Clubs", "Online Communities", "Beginner Guides", "Advanced Techniques", "Project Showcase", "Tool Reviews", "Material Guides", "Creator Spotlights", "Trend Reports"], "terminology": ["crafting technique", "material sourcing", "skill progression", "pattern design", "finishing methods", "tool maintenance", "project planning", "creative process", "handmade", "custom design", "restoration", "upcycling"], "ctas": ["Try Tutorial", "Join Community", "Share Project", "Browse Gallery", "Take Class", "Get Supplies", "Start Creating", "Connect", "Post Work", "Find Group", "Download Pattern", "Watch Video"], "engagement": ["project inspiration board", "skill tracker", "pattern generator", "supply calculator", "community gallery", "tutorial finder"], "sidebar": ["featured makers", "upcoming workshops", "craft trends", "new tutorials", "community picks", "supply deals", "event calendar", "member spotlights", "popular projects"]}'),

    -- Home and Garden Category
    ('home-and-garden',
     'Home and Garden',
     'Home improvement, gardening, DIY guides, landscaping, and decor resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Home and Garden" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Home and Garden"
- Description: Home improvement, gardening, DIY guides, landscaping, and decor resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Home and Garden" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "DIY Projects", "Garden Design", "Plant Care".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Home and Garden" category. Consider themes similar to: "Home Improvement", "Garden Planning", "Seasonal Tasks".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "hardscaping", "composting", "pruning techniques".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Plan Project", "Get Design Ideas", "Read Guide".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Home and Garden" sector. Ideas similar but not limited to: "garden layout planner".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "seasonal gardening tips", "DIY success stories", "plant care guides".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["DIY Projects", "Garden Design", "Plant Care", "Home Improvement", "Landscaping", "Shop", "About", "Blog", "Contact", "Tools", "Ideas", "Experts"], "section_themes": ["Home Improvement", "Garden Planning", "Seasonal Tasks", "Design Ideas", "Plant Guides", "Tool Reviews", "Landscaping Tips", "Interior Design", "Outdoor Living", "Sustainability"], "terminology": ["hardscaping", "composting", "pruning techniques", "soil amendment", "perennial", "annual", "mulching", "drainage", "renovation", "energy efficiency", "curb appeal", "load-bearing"], "ctas": ["Plan Project", "Get Design Ideas", "Read Guide", "Shop Tools", "Find Expert", "Calculate Materials", "Start Planning", "Get Quote", "Browse Ideas", "Watch Tutorial", "Download Plan", "Ask Expert"], "engagement": ["garden layout planner", "plant identifier", "project cost calculator", "seasonal task calendar", "design visualizer", "material estimator"], "sidebar": ["seasonal gardening tips", "DIY success stories", "plant care guides", "featured projects", "expert advice", "tool reviews", "before & after", "trending ideas", "local resources"]}'),

    -- Law, Government, & Politics Category
    ('law-government-and-politics',
     'Law, Government, & Politics',
     'Legal information, political organizations, government affairs, and civic engagement resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Law, Government, & Politics" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Law, Government, & Politics"
- Description: Legal information, political organizations, government affairs, and civic engagement resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Law, Government, & Politics" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Legal Aid", "Policy Center", "Elections".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Law, Government, & Politics" category. Consider themes similar to: "Legal Rights", "Policy Analysis", "Community Advocacy".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "constitutional rights", "legislative process", "civic participation".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Get Legal Aid", "Register to Vote", "Join Advocacy".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Law, Government, & Politics" sector. Ideas similar but not limited to: "legislation tracker".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "policy updates", "election calendar", "community events".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Legal Aid", "Policy Center", "Elections", "News", "Resources", "Advocacy", "About", "Contact", "Events", "Research", "Donate", "Volunteer"], "section_themes": ["Legal Rights", "Policy Analysis", "Community Advocacy", "Voter Information", "Legislative Updates", "Civil Liberties", "Legal Resources", "Political Analysis", "Grassroots Organizing", "Public Interest"], "terminology": ["constitutional rights", "legislative process", "civic participation", "ballot measure", "litigation", "precedent", "due process", "advocacy", "lobbying", "referendum", "jurisdiction", "statute"], "ctas": ["Get Legal Aid", "Register to Vote", "Join Advocacy", "Find Resources", "Take Action", "Learn Rights", "Contact Representative", "Sign Petition", "Donate", "Volunteer", "Subscribe", "Share"], "engagement": ["legislation tracker", "voter registration check", "rights quiz", "representative finder", "policy comparison", "election calendar"], "sidebar": ["policy updates", "election calendar", "community events", "legal resources", "action alerts", "research reports", "advocacy wins", "volunteer opportunities", "trending issues"]}'),

    -- News/Weather/Information Category
    ('news-weather-information',
     'News/Weather/Information',
     'News outlets, weather forecasts, breaking news, and general information resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "News/Weather/Information" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "News/Weather/Information"
- Description: News outlets, weather forecasts, breaking news, and general information resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "News/Weather/Information" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Breaking News", "Weather", "Local".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "News/Weather/Information" category. Consider themes similar to: "Current Events", "Weather Forecasts", "Investigative Reports".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "lead story", "weather patterns", "fact-checking".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Read Full Story", "Watch Weather", "Get Alerts".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "News/Weather/Information" sector. Ideas similar but not limited to: "weather radar".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "top headlines", "weather outlook", "community news".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Breaking News", "Weather", "Local", "National", "World", "Opinion", "Sports", "Business", "About", "Contact", "Subscribe", "Archive"], "section_themes": ["Current Events", "Weather Forecasts", "Investigative Reports", "Local Coverage", "National News", "World Affairs", "Opinion & Analysis", "Breaking Stories", "Feature Articles", "Data Journalism"], "terminology": ["lead story", "weather patterns", "fact-checking", "breaking news", "editorial", "op-ed", "byline", "headline", "source", "correspondent", "investigative", "exclusive"], "ctas": ["Read Full Story", "Watch Weather", "Get Alerts", "Subscribe", "Share Story", "Follow Topic", "Watch Live", "Read More", "View Forecast", "Sign Up", "Download App", "Submit Tip"], "engagement": ["weather radar", "news alert customizer", "topic tracker", "live stream player", "interactive map", "poll widget"], "sidebar": ["top headlines", "weather outlook", "community news", "trending stories", "most read", "opinion pieces", "photo galleries", "video highlights", "upcoming events"]}'),

    -- Non-Profit/Charity Category
    ('non-profit-charity',
     'Non-Profit/Charity',
     'Charitable organizations, non-profit initiatives, volunteering, and fundraising resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Non-Profit/Charity" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Non-Profit/Charity"
- Description: Charitable organizations, non-profit initiatives, volunteering, and fundraising resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Non-Profit/Charity" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Our Mission", "Programs", "Donate".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Non-Profit/Charity" category. Consider themes similar to: "Impact Stories", "Volunteer Opportunities", "Community Programs".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "501(c)(3) status", "community outreach", "impact measurement".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Make Donation", "Volunteer Today", "Join Event".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Non-Profit/Charity" sector. Ideas similar but not limited to: "donation tracker".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "impact reports", "volunteer spotlights", "upcoming fundraisers".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Our Mission", "Programs", "Donate", "Volunteer", "Events", "Impact", "About", "Contact", "Blog", "Partners", "News", "Get Help"], "section_themes": ["Impact Stories", "Volunteer Opportunities", "Community Programs", "Fundraising Events", "Partnership Highlights", "Beneficiary Stories", "Organization News", "Resource Center", "Advocacy Initiatives", "Annual Reports"], "terminology": ["501(c)(3) status", "community outreach", "impact measurement", "charitable giving", "grant funding", "volunteer hours", "beneficiary", "stewardship", "endowment", "sustainability", "capacity building", "advocacy"], "ctas": ["Make Donation", "Volunteer Today", "Join Event", "Get Involved", "Give Now", "Support Cause", "Register", "Start Giving", "Host Fundraiser", "Contact Us", "Learn More", "Take Action"], "engagement": ["donation tracker", "volunteer signup", "impact calculator", "event registration", "giving portal", "volunteer hour logger"], "sidebar": ["impact reports", "volunteer spotlights", "upcoming fundraisers", "success stories", "partner highlights", "donor recognition", "event calendar", "newsletter signup", "recent news"]}'),

    -- Personal Finance Category
    ('personal-finance',
     'Personal Finance',
     'Banking, investing, budgeting, savings, credit, and personal money management resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Personal Finance" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Personal Finance"
- Description: Banking, investing, budgeting, savings, credit, and personal money management resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Personal Finance" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Budget Planner", "Investment", "Credit".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Personal Finance" category. Consider themes similar to: "Financial Planning", "Investment Strategies", "Debt Management".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "compound interest", "diversification", "tax optimization".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Create Budget", "Start Investing", "Check Credit".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Personal Finance" sector. Ideas similar but not limited to: "retirement calculator".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "market updates", "financial planning tips", "rate comparisons".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Budget Planner", "Investment", "Credit", "Banking", "Insurance", "Retirement", "About", "Tools", "Blog", "Contact", "Resources", "Calculator"], "section_themes": ["Financial Planning", "Investment Strategies", "Debt Management", "Retirement Planning", "Credit Improvement", "Savings Goals", "Tax Planning", "Insurance Options", "Wealth Building", "Emergency Fund"], "terminology": ["compound interest", "diversification", "tax optimization", "asset allocation", "credit score", "APY", "portfolio", "liquidity", "amortization", "capital gains", "risk tolerance", "net worth"], "ctas": ["Create Budget", "Start Investing", "Check Credit", "Open Account", "Calculate", "Compare Rates", "Get Quote", "Plan Retirement", "Apply Now", "Learn More", "Talk to Advisor", "Download Guide"], "engagement": ["retirement calculator", "budget planner", "loan calculator", "credit score simulator", "investment comparison", "savings goal tracker"], "sidebar": ["market updates", "financial planning tips", "rate comparisons", "expert insights", "calculator tools", "educational articles", "success stories", "product reviews", "trending topics"]}'),

    -- Pets Category
    ('pets',
     'Pets',
     'Pet care, adoption, veterinary resources, training, and animal rescue information.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Pets" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Pets"
- Description: Pet care, adoption, veterinary resources, training, and animal rescue information.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Pets" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Adopt a Pet", "Pet Care", "Veterinary".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Pets" category. Consider themes similar to: "Available Pets", "Pet Health", "Training Tips".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "animal behavior", "preventive care", "nutrition requirements".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Adopt Today", "Schedule Vet Visit", "Book Training".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Pets" sector. Ideas similar but not limited to: "pet compatibility quiz".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "adoption success stories", "pet health tips", "rescue spotlights".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Adopt a Pet", "Pet Care", "Veterinary", "Training", "Shop", "Community", "About", "Contact", "Blog", "Events", "Resources", "Find Help"], "section_themes": ["Available Pets", "Pet Health", "Training Tips", "Adoption Stories", "Breed Guides", "Nutrition Advice", "Behavior Help", "Senior Pet Care", "Emergency Info", "Pet Safety"], "terminology": ["animal behavior", "preventive care", "nutrition requirements", "vaccination schedule", "microchipping", "spay/neuter", "socialization", "positive reinforcement", "enrichment", "wellness exam", "breed characteristics", "rescue"], "ctas": ["Adopt Today", "Schedule Vet Visit", "Book Training", "Find Pet", "Make Appointment", "Search Adoptables", "Get Supplies", "Contact Shelter", "Donate", "Volunteer", "Read Guide", "Learn More"], "engagement": ["pet compatibility quiz", "adoption search", "care guide finder", "vaccination tracker", "appointment scheduler", "pet name generator"], "sidebar": ["adoption success stories", "pet health tips", "rescue spotlights", "training advice", "event calendar", "volunteer opportunities", "featured pets", "product reviews", "community photos"]}'),

    -- Real Estate Category
    ('real-estate',
     'Real Estate',
     'Property listings, real estate agencies, home buying, rentals, and mortgage resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Real Estate" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Real Estate"
- Description: Property listings, real estate agencies, home buying, rentals, and mortgage resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Real Estate" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Property Search", "Buy", "Mortgages".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Real Estate" category. Consider themes similar to: "Featured Listings", "Market Analysis", "Buyer Resources".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "comparative market analysis", "closing costs", "property disclosure".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Search Properties", "Get Pre-Approved", "Find Agent".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Real Estate" sector. Ideas similar but not limited to: "mortgage pre-qualifier".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "market trends", "new listings", "featured agents".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Property Search", "Buy", "Mortgages", "Sell", "Rent", "Agents", "About", "Contact", "Blog", "Resources", "Market", "Calculator"], "section_themes": ["Featured Listings", "Market Analysis", "Buyer Resources", "Seller Guide", "Neighborhood Guide", "Mortgage Options", "Investment Properties", "First-Time Buyers", "Luxury Homes", "Open Houses"], "terminology": ["comparative market analysis", "closing costs", "property disclosure", "escrow", "pre-approval", "appraisal", "title insurance", "contingency", "earnest money", "listing price", "days on market", "square footage"], "ctas": ["Search Properties", "Get Pre-Approved", "Find Agent", "List Property", "Calculate Payment", "Schedule Tour", "Request Info", "Contact Agent", "View Details", "Save Search", "Get Valuation", "Start Search"], "engagement": ["mortgage pre-qualifier", "home value estimator", "affordability calculator", "property comparison", "neighborhood finder", "open house scheduler"], "sidebar": ["market trends", "new listings", "featured agents", "price reductions", "open houses", "mortgage rates", "buyer tips", "seller advice", "neighborhood spotlights"]}'),

    -- Religion and Spirituality Category
    ('religion-and-spirituality',
     'Religion and Spirituality',
     'Religious organizations, spiritual resources, faith communities, and worship services.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Religion and Spirituality" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Religion and Spirituality"
- Description: Religious organizations, spiritual resources, faith communities, and worship services.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Religion and Spirituality" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Our Faith", "Services", "Events".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Religion and Spirituality" category. Consider themes similar to: "Spiritual Teachings", "Community Events", "Youth Programs".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "spiritual practice", "communal worship", "faith formation".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Join Worship", "Attend Event", "Volunteer".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Religion and Spirituality" sector. Ideas similar but not limited to: "event registration".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "weekly announcements", "inspirational messages", "community highlights".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Our Faith", "Services", "Events", "Ministries", "Community", "Resources", "About", "Contact", "Give", "Media", "Youth", "Outreach"], "section_themes": ["Spiritual Teachings", "Community Events", "Youth Programs", "Outreach Ministry", "Service Times", "Study Groups", "Volunteer Opportunities", "Faith Formation", "Music Ministry", "Community Support"], "terminology": ["spiritual practice", "communal worship", "faith formation", "ministry", "fellowship", "congregation", "outreach", "meditation", "prayer", "scripture", "sermon", "sacrament"], "ctas": ["Join Worship", "Attend Event", "Volunteer", "Give Online", "Connect", "Find Group", "Watch Service", "Register", "Contact Pastor", "Learn More", "Get Involved", "Sign Up"], "engagement": ["event registration", "service live stream", "prayer request form", "group finder", "giving portal", "devotional calendar"], "sidebar": ["weekly announcements", "inspirational messages", "community highlights", "upcoming events", "service schedule", "ministry updates", "volunteer opportunities", "recent sermons", "member stories"]}'),

    -- Science Category
    ('science',
     'Science',
     'Scientific research, discoveries, STEM education, and science news.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Science" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Science"
- Description: Scientific research, discoveries, STEM education, and science news.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Science" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Research", "Publications", "Education".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Science" category. Consider themes similar to: "Research Findings", "STEM Resources", "Educational Programs".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "methodological rigor", "statistical significance", "peer validation".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Read Research", "Attend Lecture", "Explore Data".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Science" sector. Ideas similar but not limited to: "data visualization tool".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "latest breakthroughs", "scientist profiles", "science news".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Research", "Publications", "Education", "News", "Labs", "Events", "About", "Contact", "Careers", "Data", "Resources", "Funding"], "section_themes": ["Research Findings", "STEM Resources", "Educational Programs", "Scientific Discovery", "Lab Highlights", "Data & Analysis", "Innovation Spotlight", "Collaboration News", "Grant Opportunities", "Career Development"], "terminology": ["methodological rigor", "statistical significance", "peer validation", "hypothesis", "controlled study", "empirical evidence", "replication", "meta-analysis", "longitudinal study", "data visualization", "citation", "breakthrough"], "ctas": ["Read Research", "Attend Lecture", "Explore Data", "Access Publication", "Join Lab", "Apply Grant", "Subscribe", "Contact Researcher", "View Results", "Download Paper", "Learn More", "Get Updates"], "engagement": ["data visualization tool", "research database search", "citation finder", "event calendar", "lab directory", "funding opportunity tracker"], "sidebar": ["latest breakthroughs", "scientist profiles", "science news", "upcoming lectures", "publication highlights", "grant deadlines", "career opportunities", "featured research", "data releases"]}'),

    -- Shopping Category
    ('shopping',
     'Shopping',
     'Online shopping, e-commerce, deals, retail products, and gift guides.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Shopping" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Shopping"
- Description: Online shopping, e-commerce, deals, retail products, and gift guides.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Shopping" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Shop", "Deals", "Cart".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Shopping" category. Consider themes similar to: "New Arrivals", "Gift Guides", "Customer Favorites".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "product reviews", "shipping options", "loyalty program".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Shop Collection", "Add to Cart", "Write Review".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Shopping" sector. Ideas similar but not limited to: "product comparison".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "trending products", "customer reviews", "flash sales".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Shop", "Deals", "Cart", "Categories", "New Arrivals", "Sale", "Account", "Help", "Contact", "Wishlist", "Orders", "Reviews"], "section_themes": ["New Arrivals", "Gift Guides", "Customer Favorites", "Seasonal Collections", "Top Rated", "Editor Picks", "Flash Sales", "Clearance", "Trending Now", "Best Sellers"], "terminology": ["product reviews", "shipping options", "loyalty program", "return policy", "price match", "stock availability", "SKU", "add to cart", "checkout", "promo code", "free shipping", "wishlist"], "ctas": ["Shop Collection", "Add to Cart", "Write Review", "Buy Now", "Save to Wishlist", "Apply Code", "View Deal", "Quick View", "Compare", "Subscribe", "Track Order", "Get Rewards"], "engagement": ["product comparison", "size guide", "style quiz", "gift finder", "price tracker", "inventory checker"], "sidebar": ["trending products", "customer reviews", "flash sales", "recently viewed", "recommendations", "top picks", "price drops", "new arrivals", "popular categories"]}'),

    -- Social Media Category
    ('social-media',
     'Social Media',
     'Platforms for social networking, sharing, messaging, and online communities.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Social Media" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Social Media"
- Description: Platforms for social networking, sharing, messaging, and online communities.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Social Media" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Feed", "Profile", "Messages".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Social Media" category. Consider themes similar to: "Trending Content", "Community Highlights", "Creator Spotlights".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "engagement metrics", "content strategy", "community management".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Create Post", "Connect", "Share Content".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Social Media" sector. Ideas similar but not limited to: "engagement analytics".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "viral trends", "influencer spotlights", "community highlights".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Feed", "Profile", "Messages", "Discover", "Notifications", "Create", "Settings", "Help", "About", "Groups", "Events", "Marketplace"], "section_themes": ["Trending Content", "Community Highlights", "Creator Spotlights", "Featured Posts", "Viral Moments", "Group Discoveries", "Event Highlights", "User Stories", "Platform Updates", "Safety Resources"], "terminology": ["engagement metrics", "content strategy", "community management", "algorithm", "viral content", "influencer", "reach", "impressions", "user-generated content", "hashtag", "trending", "organic growth"], "ctas": ["Create Post", "Connect", "Share Content", "Follow", "Join Group", "Go Live", "Send Message", "Explore", "React", "Comment", "Subscribe", "Discover"], "engagement": ["engagement analytics", "content scheduler", "follower insights", "trending tracker", "hashtag analyzer", "community finder"], "sidebar": ["viral trends", "influencer spotlights", "community highlights", "suggested follows", "trending hashtags", "live streams", "group recommendations", "event invites", "sponsored content"]}'),

    -- Society Category
    ('society',
     'Society',
     'Social issues, advocacy, cultural organizations, and community initiatives.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Society" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Society"
- Description: Social issues, advocacy, cultural organizations, and community initiatives.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Society" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Issues", "Campaigns", "Events".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Society" category. Consider themes similar to: "Current Issues", "Advocacy Actions", "Volunteer Opportunities".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "social justice", "community organizing", "equity initiatives".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Join Movement", "Volunteer", "Spread Awareness".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Society" sector. Ideas similar but not limited to: "petition signer".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "breaking news", "activist spotlights", "community impact".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Issues", "Campaigns", "Events", "Resources", "News", "Volunteer", "About", "Contact", "Donate", "Community", "Action", "Join"], "section_themes": ["Current Issues", "Advocacy Actions", "Volunteer Opportunities", "Community Stories", "Campaign Updates", "Resource Center", "Policy Impact", "Grassroots Efforts", "Success Stories", "Movement News"], "terminology": ["social justice", "community organizing", "equity initiatives", "grassroots", "coalition building", "systemic change", "advocacy", "stakeholder engagement", "collective action", "awareness campaign", "inclusion", "empowerment"], "ctas": ["Join Movement", "Volunteer", "Spread Awareness", "Take Action", "Sign Petition", "Donate Now", "Contact Rep", "Share Story", "Register", "Get Involved", "Learn More", "Stand With Us"], "engagement": ["petition signer", "action tracker", "event finder", "representative locator", "volunteer matcher", "impact calculator"], "sidebar": ["breaking news", "activist spotlights", "community impact", "action alerts", "event calendar", "success stories", "resource guides", "partner organizations", "movement updates"]}'),

    -- Sports Category
    ('sports',
     'Sports',
     'Sports news, team updates, scores, events, and athletic resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Sports" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Sports"
- Description: Sports news, team updates, scores, events, and athletic resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Sports" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Scores", "Teams", "Schedule".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Sports" category. Consider themes similar to: "Live Scores", "Team News", "Player Stats".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "player statistics", "game strategy", "sports analytics".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Watch Game", "Buy Tickets", "Join Fan Club".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Sports" sector. Ideas similar but not limited to: "live scoreboard".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "game highlights", "player interviews", "league standings".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Scores", "Teams", "Schedule", "News", "Stats", "Videos", "Tickets", "Shop", "About", "Standings", "Fantasy", "Podcasts"], "section_themes": ["Live Scores", "Team News", "Player Stats", "Game Analysis", "Highlights", "Injury Reports", "Trade Rumors", "Draft Coverage", "Championship News", "Historical Records"], "terminology": ["player statistics", "game strategy", "sports analytics", "playoff standings", "draft pick", "free agency", "contract extension", "roster move", "winning streak", "season record", "MVP candidate", "championship"], "ctas": ["Watch Game", "Buy Tickets", "Join Fan Club", "View Stats", "Follow Team", "Read Analysis", "Watch Highlights", "Get Alerts", "Check Scores", "Subscribe", "Shop Gear", "Enter Contest"], "engagement": ["live scoreboard", "fantasy league", "bracket challenge", "stat comparison", "schedule planner", "ticket finder"], "sidebar": ["game highlights", "player interviews", "league standings", "top performers", "upcoming games", "trade news", "fan polls", "podcast episodes", "photo galleries"]}'),

    -- Style & Fashion Category
    ('style-and-fashion',
     'Style & Fashion',
     'Fashion trends, style guides, beauty resources, and clothing inspiration.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Style & Fashion" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Style & Fashion"
- Description: Fashion trends, style guides, beauty resources, and clothing inspiration.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Style & Fashion" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Trends", "Style Guide", "Beauty".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Style & Fashion" category. Consider themes similar to: "Seasonal Trends", "Wardrobe Essentials", "Designer Spotlights".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "capsule wardrobe", "sustainable fashion", "personal styling".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Shop Collection", "Get Beauty Tips", "Book Stylist".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Style & Fashion" sector. Ideas similar but not limited to: "outfit generator".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "trend forecasts", "stylist interviews", "fashion week highlights".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Trends", "Style Guide", "Beauty", "Shop", "Designers", "News", "About", "Contact", "Blog", "Collections", "Looks", "Magazine"], "section_themes": ["Seasonal Trends", "Wardrobe Essentials", "Designer Spotlights", "Beauty Tips", "Street Style", "Fashion Week", "Sustainable Fashion", "Accessories Guide", "Celebrity Style", "Runway Reports"], "terminology": ["capsule wardrobe", "sustainable fashion", "personal styling", "haute couture", "ready-to-wear", "color palette", "silhouette", "accessorizing", "trend forecast", "lookbook", "editorial", "collection"], "ctas": ["Shop Collection", "Get Beauty Tips", "Book Stylist", "View Lookbook", "Explore Trends", "Read Style Guide", "Watch Show", "Get Inspired", "Try Look", "Subscribe", "Follow Designer", "Share Style"], "engagement": ["outfit generator", "style quiz", "virtual try-on", "color matcher", "wardrobe planner", "trend tracker"], "sidebar": ["trend forecasts", "stylist interviews", "fashion week highlights", "editor picks", "beauty reviews", "celebrity looks", "sustainable picks", "new arrivals", "must-haves"]}'),

    -- Technology & Computing Category
    ('technology-and-computing',
     'Technology & Computing',
     'Tech news, software and hardware reviews, gadgets, and computing resources.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Technology & Computing" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Technology & Computing"
- Description: Tech news, software and hardware reviews, gadgets, and computing resources.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Technology & Computing" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Reviews", "Downloads", "Support".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Technology & Computing" category. Consider themes similar to: "Product Reviews", "How-To Guides", "Tech News".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "user interface", "compatibility matrix", "security protocols".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Read Review", "Download Software", "Get Support".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Technology & Computing" sector. Ideas similar but not limited to: "system compatibility checker".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "product launches", "developer spotlights", "tech tutorials".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Reviews", "Downloads", "Support", "News", "Guides", "Forums", "About", "Contact", "Shop", "Tutorials", "Compare", "Deals"], "section_themes": ["Product Reviews", "How-To Guides", "Tech News", "Software Updates", "Hardware Reviews", "Security Tips", "Comparison Guides", "Troubleshooting", "Industry Trends", "Developer Resources"], "terminology": ["user interface", "compatibility matrix", "security protocols", "firmware update", "API integration", "cloud computing", "open source", "encryption", "bandwidth", "latency", "scalability", "debugging"], "ctas": ["Read Review", "Download Software", "Get Support", "Compare Products", "Watch Tutorial", "Join Forum", "Try Free", "Buy Now", "Get Started", "Contact Support", "Learn More", "Subscribe"], "engagement": ["system compatibility checker", "product comparison", "spec finder", "troubleshooter", "download manager", "benchmark tool"], "sidebar": ["product launches", "developer spotlights", "tech tutorials", "hot deals", "community picks", "security alerts", "version updates", "editor reviews", "trending topics"]}'),

    -- Travel Category
    ('travel',
     'Travel',
     'Travel guides, destinations, booking resources, and tourism tips.',
     1,
     'Create a **complete, polished, production-quality** primary web page for a new client in the "Travel" sector.
Your goal is to generate the full HTML code for a page that is not just functional but also visually compelling, content-rich, and feels like a finished product ready for launch.

**Client & Category:**
- Industry: "Travel"
- Description: Travel guides, destinations, booking resources, and tourism tips.

**Your Creative Task:**
1.  **Invent:** Create a unique, professional-sounding site name and a strong tagline fitting the "Travel" category.
2.  **Define Page:** Determine the most effective primary page type (e.g., homepage, service landing page, category portal) to showcase this fictional entity.
3.  **Design:** Develop an opinionated, modern, and professional layout. Make distinct choices about structure and flow.

**Content & Structure Requirements (Deliver a COMPLETE page):**
-   **Overall:** The final page must feel substantial and complete, with realistic amounts of text (multiple paragraphs per section where appropriate, avoid single sentences), well-integrated placeholder images, and logical flow. It should look like a real website a business would proudly use.
-   **HEADER:** Include the invented site name, tagline, a logo placeholder image, and a primary navigation bar. Ensure the navigation has **at least 5-7 clearly defined, relevant links** including: "Destinations", "Trip Planner", "Travel Deals".
-   **MAIN CONTENT:** Structure this area with **at least 3-4 distinct, well-developed sections**.
    -   Address key topics relevant to the "Travel" category. Consider themes similar to: "Destination Guides", "Adventure Travel", "Cultural Experiences".
    -   **Content Depth:** Populate each section with **substantial, realistic text** (multiple sentences/paragraphs). Use authentic industry language and terminology like: "cultural etiquette", "visa requirements", "off-the-beaten-path".
    -   **Visuals:** Integrate relevant placeholder images logically within the content sections.
    -   **Calls to Action:** Include clear and contextually relevant CTAs. Use strong verbs similar to: "Book Adventure", "Plan Itinerary", "Find Deals".
-   **ENGAGEMENT (Recommended):** Strongly consider incorporating **one meaningful interactive element** that would genuinely benefit a user in the "Travel" sector. Ideas similar but not limited to: "destination comparison".
-   **SIDEBAR (Optional):** If your design includes a sidebar, populate it with **useful, relevant content**. Ideas: "travel hacks", "destination spotlights", "traveler reviews".
-   **FOOTER:** Include a professional footer with invented contact details, copyright (current year), social media links, and standard links (Privacy, Terms).
-   **MODERN WEB PATTERNS:** Include modern web patterns like testimonial cards, feature grids, or FAQ accordions where appropriate.',
     '{"nav_links": ["Destinations", "Trip Planner", "Travel Deals", "Hotels", "Flights", "Experiences", "About", "Contact", "Blog", "Guides", "Reviews", "Bookings"], "section_themes": ["Destination Guides", "Adventure Travel", "Cultural Experiences", "Travel Tips", "Hotel Reviews", "Flight Deals", "Budget Travel", "Luxury Escapes", "Family Vacations", "Solo Travel"], "terminology": ["cultural etiquette", "visa requirements", "off-the-beaten-path", "itinerary", "layover", "travel insurance", "all-inclusive", "eco-tourism", "travel advisory", "baggage allowance", "booking", "excursion"], "ctas": ["Book Adventure", "Plan Itinerary", "Find Deals", "Search Flights", "Reserve Hotel", "Explore Destination", "Get Quote", "Compare Prices", "Book Now", "Read Guide", "Subscribe", "Start Planning"], "engagement": ["destination comparison", "trip planner", "budget calculator", "packing list generator", "flight tracker", "currency converter"], "sidebar": ["travel hacks", "destination spotlights", "traveler reviews", "deal alerts", "inspiration gallery", "seasonal picks", "visa info", "weather forecasts", "trending destinations"]}');
