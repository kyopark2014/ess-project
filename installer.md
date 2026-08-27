# AWS Infrastructure Installer

boto3를 사용하여 AWS 인프라 리소스를 생성하는 Python 스크립트입니다.

## 목차

1. [개요](#개요)
2. [설정값](#설정값)
3. [생성되는 리소스](#생성되는-리소스)
4. [주요 함수](#주요-함수)
5. [실행 방법](#실행-방법)
6. [배포 순서](#배포-순서)

---

## 개요

이 스크립트는 Agent Skills 애플리케이션에 필요한 AWS 백엔드 리소스를 자동으로 생성합니다. 애플리케이션은 로컬에서 `./run_local.sh` 또는 `uvicorn application.server:app --host 0.0.0.0 --port 8501`로 실행합니다.

### 주요 특징
- **완전 자동화**: 단일 스크립트로 백엔드 인프라 배포
- **멱등성**: 이미 존재하는 리소스는 재사용
- **에러 핸들링**: 각 단계별 예외 처리
- **로깅**: 상세한 배포 진행 상황 출력

---

## 설정값

```python
# 기본 설정
project_name = "agent-skills"          # 프로젝트 이름 (최소 3자)
region = "us-west-2"                   # AWS 리전

cloudfront_comment = "CloudFront-for-rag-project"
oai_comment = f"OAI for {project_name}"

# 자동 생성되는 변수
account_id = sts_client.get_caller_identity()["Account"]
bucket_name = f"storage-for-rag-project-{account_id}-{region}"
vector_index_name = project_name
```

---

## 생성되는 리소스

### 1. S3 버킷
- **이름**: `storage-for-rag-project-{account_id}-{region}`
- **설정**:
  - CORS 활성화 (GET, POST, PUT)
  - 퍼블릭 액세스 차단
  - `docs/{project_name}/` 폴더 자동 생성

### 2. IAM 역할

| 역할 | 설명 |
|------|------|
| `role-knowledge-base-for-{project_name}-{region}` | Bedrock Knowledge Base용 역할 |
| `role-agent-for-{project_name}-{region}` | Bedrock Agent용 역할 |
| `role-agentcore-memory-for-{project_name}-{region}` | AgentCore Memory용 역할 |
| `role-agentcore-gateway-websearch-for-{project_name}` | AgentCore Web Search Gateway용 역할 |

### 3. Secrets Manager
공유 시크릿(프로젝트명 접미사 없음). 이미 있으면 재사용합니다.
- `openweathermap`: Weather API 키
- `notionapikey`: Notion API 키
- `telegramapikey`: Telegram Bot API 키
- `discordapikey`: Discord Bot API 키
- `slackapikey`: Slack API 키

### 4. OpenSearch Serverless
- **컬렉션 이름**: `{project_name}` (프로젝트 전용)
- **정책**: `enc-{project_name}-{region}`, `net-{project_name}-{region}`, `data-{project_name}`
- **인덱스**: KNN 벡터 검색 인덱스 (1024차원, 이름=`{project_name}`)

### 5. Bedrock Knowledge Base
- **이름**: `{project_name}` (프로젝트 전용)
- **스토리지**: OpenSearch Serverless
- **임베딩 모델**: Amazon Titan Embed Text v2 (1024차원)
- **파싱 모델**: Claude Sonnet 4.6 (Foundation Model Parser)
- **청킹**: Hierarchical (1500/300 토큰)
- **데이터 소스**: S3 `docs/{project_name}/` 접두사

### 6. CloudFront (S3 오리진)
- **Comment**: `CloudFront-for-rag-project`
- **오리진**: S3 버킷 (`docs/{project_name}/` 등 정적 컨텐츠 공유용)
- **OAI**: S3 버킷 정책으로 CloudFront 접근 허용
- **sharing_url**: `https://{cloudfront_domain}` → `application/config.json`에 저장

### 7. AgentCore Web Search Gateway
- **Gateway**: `gateway-websearch` (`us-east-1`)
- **Target**: 관리형 `web-search` 커넥터

---

## 주요 함수

### 인프라 생성 함수

#### `create_s3_bucket()`
S3 버킷 생성 및 CORS, 퍼블릭 액세스 차단 설정

#### `create_iam_role()`
IAM 역할 생성 및 관리형 정책 연결

#### `create_opensearch_collection()`
OpenSearch Serverless 컬렉션 및 보안 정책 생성

#### `create_knowledge_base_with_opensearch()`
Bedrock Knowledge Base 생성

#### `create_cloudfront_distribution()`
S3 오리진 CloudFront 배포 생성 (OAI + 버킷 정책)

#### `get_or_create_agentcore_websearch_gateway()`
AgentCore Web Search Gateway 및 Target 생성

#### `build_app_environment()` / `write_application_config()`
`application/config.json` 생성 및 갱신

---

## 실행 방법

### 인프라 배포

```bash
python installer.py
```

### 로컬 애플리케이션 실행

```bash
./run_local.sh
# 또는
uvicorn application.server:app --host 0.0.0.0 --port 8501
```

---

## 배포 순서

```
[1/6] Secrets Manager 시크릿 생성
       ↓
[2/6] S3 버킷 생성
       ↓
[3/6] IAM 역할 생성
       • Knowledge Base / Agent / AgentCore Memory 역할
       • AgentCore Web Search Gateway 역할 및 Gateway 생성
       ↓
[4/6] OpenSearch Serverless 컬렉션 생성
       ↓
[5/6] Bedrock Knowledge Base 생성
       ↓
[6/6] CloudFront 배포 생성 (S3 오리진)
       ↓
application/config.json 업데이트 (sharing_url 포함)
```

---

## 배포 완료 후

```
================================================================
Infrastructure Deployment Completed Successfully!
================================================================
Summary:
  S3 Bucket: storage-for-rag-project-{account_id}-us-west-2
  CloudFront Domain: https://xxxxxxxxx.cloudfront.net
  OpenSearch Endpoint: https://xxxxxxxx.us-west-2.aoss.amazonaws.com
  Knowledge Base ID: XXXXXXXXXX

Total deployment time: XX.XX minutes
================================================================
Run locally: ./run_local.sh (uvicorn :8501)
Note: CloudFront distribution may take 15-20 minutes to fully deploy
================================================================
```

### 주의사항
- `application/config.json` 파일이 자동으로 업데이트됩니다 (`sharing_url` 포함)
- Gateway는 `us-east-1`에 생성되며, 애플리케이션 리전과 다를 수 있습니다
- `docs/{project_name}/` 등 S3 정적 파일은 CloudFront URL로 공유됩니다

---

## 에러 처리

| 상황 | 처리 방법 |
|------|----------|
| 리소스 이미 존재 | 기존 리소스 재사용 |
| 정책 이미 존재 | 기존 정책 업데이트 |
| 타임아웃 | 재시도 로직 적용 |

배포 실패 시 상세한 에러 메시지와 스택 트레이스가 출력됩니다.
