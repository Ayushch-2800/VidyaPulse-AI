---


---

<h2 id="phase-1-architectural-foundation--database-infrastructure">Phase 1: Architectural Foundation &amp; Database Infrastructure</h2>
<h3 id="task-1-repository-initialization--environment-architecture">Task 1: Repository Initialization &amp; Environment Architecture</h3>
<ul>
<li>
<p><strong>Objective:</strong> Establish the production monorepo structure, environment configurations, and core development dependencies.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Initialize a Git repository with <code>apps/web</code> (Next.js/React frontend), <code>apps/server</code> (FastAPI/Python backend), and <code>packages/shared</code> (shared TypeScript/Python schemas).</p>
</li>
<li>
<p>Define environment variable templates (<code>.env.example</code>) containing keys for PostgreSQL, Supabase, Sarvam AI/Bhashini, and OpenAI/Gemini endpoints.</p>
</li>
<li>
<p>Configure code linting, formatting (Prettier, Black, ESLint), and git hooks (Husky) to enforce code standards.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Fully initialized workspace running baseline development servers on frontend and backend ports.</p>
</li>
</ul>
<h3 id="task-2-database-schema--vector-extension-configuration">Task 2: Database Schema &amp; Vector Extension Configuration</h3>
<ul>
<li>
<p><strong>Objective:</strong> Design and deploy the relational schema with <code>pgvector</code> enabled for semantic vector storage.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Deploy a PostgreSQL instance via Supabase/Docker and execute <code>CREATE EXTENSION IF NOT EXISTS vector;</code>.</p>
</li>
<li>
<p>Create core database tables:</p>
<ul>
<li>
<p><code>users</code> (id, email, preferred_language, created_at)</p>
</li>
<li>
<p><code>lectures</code> (id, user_id, source_type, external_url, duration, title, status)</p>
</li>
<li>
<p><code>transcript_chunks</code> (id, lecture_id, start_time, end_time, text_content, language, embedding <code>vector(1536)</code>)</p>
</li>
<li>
<p><code>visual_chunks</code> (id, lecture_id, timestamp, frame_url, extracted_text, formula_markdown, embedding <code>vector(1536)</code>)</p>
</li>
</ul>
</li>
<li>
<p>Create HNSW or IVFFlat vector indexes on <code>embedding</code> columns for rapid cosine distance searching.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Executable SQL migration files applied successfully to the database.</p>
</li>
</ul>
<h3 id="task-3-authentication--multi-tenant-user-management">Task 3: Authentication &amp; Multi-Tenant User Management</h3>
<ul>
<li>
<p><strong>Objective:</strong> Implement secure JWT-based authentication and user session management.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Configure Supabase Auth / NextAuth.js for email/password and Google OAuth logins.</p>
</li>
<li>
<p>Implement Row Level Security (RLS) policies on database tables to ensure users can only access their own lecture records and workspace artifacts.</p>
</li>
<li>
<p>Create backend middleware in FastAPI to validate bearer tokens on incoming API routes.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Secure authentication flow allowing sign-up, sign-in, and token-protected API routes.</p>
</li>
</ul>
<h3 id="task-4-storage-infrastructure--media-bucket-setup">Task 4: Storage Infrastructure &amp; Media Bucket Setup</h3>
<ul>
<li>
<p><strong>Objective:</strong> Configure cloud object storage for binary media, extracted video keyframes, and generated PDF notes.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Create private cloud buckets (<code>lectures-audio</code>, <code>lecture-keyframes</code>, <code>student-exports</code>).</p>
</li>
<li>
<p>Configure Signed URL generation policies so the frontend can securely upload/view files without public bucket access.</p>
</li>
<li>
<p>Implement lifecycle rules to automatically prune raw temporary audio files after vectorization to minimize storage costs.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Functional storage module capable of issuing secure upload/download URLs.</p>
</li>
</ul>
<h2 id="phase-2-multi-source-ingestion--extraction-engine">Phase 2: Multi-Source Ingestion &amp; Extraction Engine</h2>
<h3 id="task-5-route-a-—-public-youtube-ingestion-pipeline">Task 5: Route A — Public YouTube Ingestion Pipeline</h3>
<ul>
<li>
<p><strong>Objective:</strong> Build the automated extraction pipeline for public YouTube lecture URLs.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Implement a URL parser and validator using <code>yt-dlp</code> to pull video metadata (title, duration, channel, thumbnail).</p>
</li>
<li>
<p>Fetch existing closed captions via <code>youtube-transcript-api</code> if available.</p>
</li>
<li>
<p>Implement a fallback trigger: if captions are missing, download the audio track (<code>.m4a</code>/<code>.mp3</code>) using <code>yt-dlp</code> and pass it to the media storage bucket.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> API endpoint <code>/api/ingest/youtube</code> accepting a link and returning video metadata plus raw audio/caption payloads.</p>
</li>
</ul>
<h3 id="task-6-route-b-—-direct-lecture-file-upload-pipeline">Task 6: Route B — Direct Lecture File Upload Pipeline</h3>
<ul>
<li>
<p><strong>Objective:</strong> Enable direct drag-and-drop processing for offline recordings and local lecture files.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Create a chunked file upload endpoint in FastAPI utilizing multipart form data for large video/audio files (<code>.mp4</code>, <code>.mkv</code>, <code>.mp3</code>).</p>
</li>
<li>
<p>Implement backend validation checking file signature, size limits (up to 2GB), and media duration.</p>
</li>
<li>
<p>Save the media payload directly to the storage bucket and publish an ingestion task to an asynchronous queue (Celery/Redis).</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Working drag-and-drop ingestion pipeline handling local audio/video uploads cleanly.</p>
</li>
</ul>
<h3 id="task-7-route-c-—-chrome-extension-companion-protected-web-players">Task 7: Route C — Chrome Extension Companion (Protected Web Players)</h3>
<ul>
<li>
<p><strong>Objective:</strong> Build a browser extension to capture live tab audio from restricted or DRM-protected lecture portals.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Scaffold a Chrome Extension (Manifest V3) with background script and popup UI.</p>
</li>
<li>
<p>Utilize <code>chrome.tabCapture</code> API to record the active tab’s audio stream in real-time.</p>
</li>
<li>
<p>Stream 30-second audio blobs via WebSockets or POST chunks to the backend ingestion queue while the user watches the lecture.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Chrome Extension capable of capturing tab audio and transmitting real-time chunks to the server.</p>
</li>
</ul>
<h3 id="task-8-video-frame-extraction--scene-change-engine">Task 8: Video Frame Extraction &amp; Scene-Change Engine</h3>
<ul>
<li>
<p><strong>Objective:</strong> Extract slide changes, whiteboard notes, and written equations from video streams using computer vision.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Integrate <code>OpenCV</code> (<code>cv2</code>) in Python to perform frame-by-frame scene transition detection (structural similarity index - SSIM thresholding).</p>
</li>
<li>
<p>Sample keyframes every time a lecturer shifts slides or writes a major new segment on a whiteboard.</p>
</li>
<li>
<p>Compress extracted keyframes, assign exact timestamps, and upload them to the <code>lecture-keyframes</code> storage bucket.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Frame processing pipeline that reduces a 2-hour video into 15–30 high-value visual keyframes.</p>
</li>
</ul>
<h2 id="phase-3-pan-india-multilingual--multimodal-ai-core">Phase 3: Pan-India Multilingual &amp; Multimodal AI Core</h2>
<h3 id="task-9-pan-india-multilingual-asr-engine-integration">Task 9: Pan-India Multilingual ASR Engine Integration</h3>
<ul>
<li>
<p><strong>Objective:</strong> Convert multi-language and code-mixed (Hinglish, Tamil-English, etc.) audio streams into time-stamped text scripts.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Integrate the <strong>Sarvam AI (Saaras v3)</strong> or <strong>Bhashini API</strong> client in the backend server.</p>
</li>
<li>
<p>Feed audio files into the ASR engine with automatic language detection enabled across 22+ Indian scheduled languages.</p>
</li>
<li>
<p>Parse the returned transcript JSON to extract word-level and sentence-level precise timestamps (<code>start_time</code>, <code>end_time</code>).</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> ASR pipeline returning fully time-coded transcripts across any regional Indian accent or dialect.</p>
</li>
</ul>
<h3 id="task-10-multimodal-visual-ocr--formula-indexing-pipeline">Task 10: Multimodal Visual OCR &amp; Formula Indexing Pipeline</h3>
<ul>
<li>
<p><strong>Objective:</strong> Extract handwritten formulas, code blocks, and diagrams from visual keyframes.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Run <code>PaddleOCR</code> or a specialized Vision-Language Model over extracted visual keyframes from Task 8.</p>
</li>
<li>
<p>Convert extracted equations and visual structures into standard LaTeX markdown strings.</p>
</li>
<li>
<p>Combine extracted visual text, LaTeX formulas, and keyframe timestamps into structured visual data payloads.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> OCR service converting visual lecture frames into structured Markdown and LaTeX strings.</p>
</li>
</ul>
<h3 id="task-11-unified-temporal-chunking-engine">Task 11: Unified Temporal Chunking Engine</h3>
<ul>
<li>
<p><strong>Objective:</strong> Align audio transcripts and visual OCR frames into synchronized temporal chunks.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Implement a sliding window chunker (e.g., 300 words with 50-word overlap).</p>
</li>
<li>
<p>Bind extracted visual keyframes and OCR data to transcript chunks sharing the exact same time window (<code>[start_time, end_time]</code>).</p>
</li>
<li>
<p>Format each chunk as a structured entity containing text, visual context, language tag, and timestamp references.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Chunking engine that outputs unified multimodal data blocks ready for vectorization.</p>
</li>
</ul>
<h3 id="task-12-multilingual-vector-embedding--store-ingestion">Task 12: Multilingual Vector Embedding &amp; Store Ingestion</h3>
<ul>
<li>
<p><strong>Objective:</strong> Convert text and visual chunks into dense vector representations and index them in <code>pgvector</code>.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Initialize a multilingual embedding model (such as <code>text-embedding-3-small</code> or an Indic-supported embedding model).</p>
</li>
<li>
<p>Batch-generate 1536-dimensional embeddings for all unified temporal chunks (audio + visual OCR context).</p>
</li>
<li>
<p>Execute bulk insert queries into <code>transcript_chunks</code> and <code>visual_chunks</code> tables in PostgreSQL.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Populated vector database table ready for sub-second semantic retrieval.</p>
</li>
</ul>
<h2 id="phase-4-query-routing-intelligence--artifact-engine">Phase 4: Query Routing, Intelligence &amp; Artifact Engine</h2>
<h3 id="task-13-hybrid-intelligent-query-router">Task 13: Hybrid Intelligent Query Router</h3>
<ul>
<li>
<p><strong>Objective:</strong> Route incoming user queries to either exact-keyword scanning or semantic vector retrieval.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Build a classifier/regex agent that inspects user questions for literal or counting intent (e.g., <em>“How many times did the teacher say X?”</em>).</p>
</li>
<li>
<p>Route 1 (Literal): Execute sequential SQL text matches across all transcript segments for the lecture, bypassing vector search.</p>
</li>
<li>
<p>Route 2 (Semantic/Visual): Generate query embeddings and perform cosine similarity search (<code>&lt;=&gt;</code> operator in <code>pgvector</code>) to pull the top 8 relevant chunks.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Query routing module returning precise context blocks for any question type.</p>
</li>
</ul>
<h3 id="task-14-grounded-llm-synthesizer-with-deep-links">Task 14: Grounded LLM Synthesizer with Deep-Links</h3>
<ul>
<li>
<p><strong>Objective:</strong> Generate accurate, cited answers backed by clickable video timestamp links.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Construct system prompts instructing the LLM to answer <em>only</em> based on retrieved contexts, citing timestamps in <code>[MM:SS]</code> format.</p>
</li>
<li>
<p>Enforce strict safety constraints: if the information is absent from the transcript/visuals, the LLM must respond with <em>“Not covered in this lecture.”</em></p>
</li>
<li>
<p>Parse generated markdown to convert <code>[MM:SS]</code> text into interactive deep-link button components.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Synthesis engine producing cited answers with functional timestamp navigation triggers.</p>
</li>
</ul>
<h3 id="task-15-automated-pyq-mapping--formula-cheat-sheet-engine">Task 15: Automated PYQ Mapping &amp; Formula Cheat-Sheet Engine</h3>
<ul>
<li>
<p><strong>Objective:</strong> Automatically extract formulas, key concepts, and cross-reference previous year exam questions (PYQs).</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Create a background worker that runs immediately after video indexing completes.</p>
</li>
<li>
<p>Use structured LLM extraction (JSON schema output) to pull all core definitions, theorems, and LaTeX formulas into a cheat-sheet model.</p>
</li>
<li>
<p>Match extracted concepts against a seeded database of JEE/NEET/UPSC/GATE exam topics to tag relevant lecture sections.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Automatic background job generating structured cheat-sheets and topic tags per lecture.</p>
</li>
</ul>
<h3 id="task-16-active-recall-flashcard--quiz-subsystem">Task 16: Active Recall Flashcard &amp; Quiz Subsystem</h3>
<ul>
<li>
<p><strong>Objective:</strong> Generate interactive study flashcards and multiple-choice quizzes from indexed lectures.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Prompt an LLM to analyze the unified lecture chunks and generate 10 high-yield study flashcards (Question, Answer, Timestamp Proof).</p>
</li>
<li>
<p>Build a quiz generation pipeline creating 5 multiple-choice questions with detailed explanations for correct/incorrect choices.</p>
</li>
<li>
<p>Save generated study sets in the <code>study_artifacts</code> database table linked to the user’s workspace.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Functioning flashcard and quiz generator integrated with database persistence.</p>
</li>
</ul>
<h2 id="phase-5-user-interface-workspaces--production-deployment">Phase 5: User Interface, Workspaces &amp; Production Deployment</h2>
<h3 id="task-17-interactive-dashboard--synced-video-player-component">Task 17: Interactive Dashboard &amp; Synced Video Player Component</h3>
<ul>
<li>
<p><strong>Objective:</strong> Build the core student dashboard with integrated video playback and synced transcript sidebars.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Build a React video player component supporting YouTube embeds, direct HTML5 video, and audio playback.</p>
</li>
<li>
<p>Implement an auto-scrolling transcript panel that highlights the current spoken paragraph in real-time as the video plays.</p>
</li>
<li>
<p>Connect timestamp deep-links from chat answers directly to the player’s <code>seekTo(seconds)</code> method.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Fully interactive React dashboard with bidirectional video-transcript synchronization.</p>
</li>
</ul>
<h3 id="task-18-multilingual-student-workspace--notes-exporter">Task 18: Multilingual Student Workspace &amp; Notes Exporter</h3>
<ul>
<li>
<p><strong>Objective:</strong> Provide workspace tools for note-taking, language switching, and exporting study materials.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Implement a regional language UI toggle (Hindi, Tamil, Telugu, Marathi, Bengali, English) that translates generated summaries and notes dynamically.</p>
</li>
<li>
<p>Add an interactive notes editor allowing students to save key AI answers, flashcards, and formulas.</p>
</li>
<li>
<p>Build a PDF export engine (<code>pdfmake</code> or HTML-to-PDF server endpoint) allowing one-click downloads of complete lecture summaries and cheat-sheets.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Full-featured study workspace supporting multi-language translation and PDF export.</p>
</li>
</ul>
<h3 id="task-19-end-to-end-testing--performance-optimization">Task 19: End-to-End Testing &amp; Performance Optimization</h3>
<ul>
<li>
<p><strong>Objective:</strong> Conduct rigorous system testing, handle edge cases, and optimize query latencies.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Write unit tests for ingestion fallback logic, chunking algorithms, and SQL query builders.</p>
</li>
<li>
<p>Implement Redis caching for query embeddings and frequent lecture searches to reduce API costs and keep response times under 1.5 seconds.</p>
</li>
<li>
<p>Conduct edge-case testing with low-quality audio, mixed regional accents, and long 4-hour lectures.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Test suite achieving &gt;80% code coverage and verified sub-2-second retrieval latency.</p>
</li>
</ul>
<h3 id="task-20-containerization-cicd-pipeline--edge-deployment">Task 20: Containerization, CI/CD Pipeline &amp; Edge Deployment</h3>
<ul>
<li>
<p><strong>Objective:</strong> Package the application into Docker containers and deploy to production cloud infrastructure.</p>
</li>
<li>
<p><strong>Workflow:</strong></p>
<ol>
<li>
<p>Write <code>Dockerfile</code> configurations for the Next.js frontend and FastAPI backend apps.</p>
</li>
<li>
<p>Create a GitHub Actions CI/CD pipeline to run tests, build container images, and deploy automatically upon pushing to the <code>main</code> branch.</p>
</li>
<li>
<p>Deploy the frontend to Vercel/AWS Amplify, the backend services to AWS ECS / Render / Modal, and connect production Supabase PostgreSQL.</p>
</li>
</ol>
</li>
<li>
<p><strong>Deliverable:</strong> Live production deployment accessible via a secure custom domain.</p>
</li>
</ul>

