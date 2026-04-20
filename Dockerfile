FROM --platform=linux/amd64 python:3.13-slim

WORKDIR /app

# Install Node.js, npm, and system dependencies
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get install -y \
        libreoffice \
        poppler-utils \
        pandoc \
        fonts-nanum && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install MCP packages globally
RUN npm install -g @modelcontextprotocol/server-filesystem

# PPT npm packages (global + local so require() works from any directory, including /tmp)
RUN npm install -g pptxgenjs sharp react react-dom react-icons docx && \
    mkdir -p /app/node_modules && \
    npm install --prefix /app pptxgenjs sharp react react-dom react-icons docx

# Allow require('pptxgenjs') to resolve from any working directory
ENV NODE_PATH=/usr/local/lib/node_modules:/app/node_modules

# Install Google Chrome (stable)
RUN curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb && \
    apt-get update && \
    apt-get install -y --no-install-recommends /tmp/chrome.deb && \
    rm /tmp/chrome.deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install mcp-server-fetch-typescript and Playwright browsers
RUN npx -y mcp-server-fetch-typescript --version 2>/dev/null || true && \
    npx playwright install --with-deps chromium

RUN pip install streamlit streamlit_paste_button
RUN pip install strands-agents strands-agents-tools bedrock-agentcore
RUN pip install langchain_aws langchain langchain_community langchain_experimental langchain-text-splitters
RUN pip install mcp 
RUN pip install tavily-python==0.5.0 pytz==2024.2 beautifulsoup4==4.12.3
RUN pip install plotly_express==0.4.1 matplotlib==3.10.0
RUN pip install PyPDF2==3.0.1 requests reportlab
RUN pip install opensearch-py 
RUN pip install pyyaml pandas numpy boto3
RUN pip install uv kaleido diagrams graphviz rich colorama finance-datareader

RUN pip install python-pptx
# Skills: docx / xlsx / pptx / myslide
RUN pip install defusedxml lxml openpyxl Pillow "markitdown[pptx]"
# Skills: pdf
RUN pip install reportlab pypdf pdfplumber PyYAML
# Skills: browser automation
RUN pip install "browser-use[cli]"

RUN mkdir -p /root/.streamlit
COPY config.toml /root/.streamlit/

COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["python", "-m", "streamlit", "run", "application/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
