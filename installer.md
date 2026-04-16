# AWS Infrastructure Installer

boto3를 사용하여 AWS 인프라 리소스를 생성하는 Python 스크립트(`installer.py`)입니다.  
CDK 스택과 동등한 AWS 인프라를 프로그래밍 방식으로 배포합니다.

## 목차

1. [개요](#개요)
2. [사전 요구 사항](#사전-요구-사항)
3. [설정값](#설정값)
4. [생성되는 리소스](#생성되는-리소스)
5. [주요 함수](#주요-함수)
6. [실행 방법](#실행-방법)
7. [배포 순서](#배포-순서)
8. [배포 완료 후](#배포-완료-후)

---

## 개요

이 스크립트는 AI 기반 채팅 애플리케이션(Streamlit + Strands Agent 등)을 위한 AWS 인프라를 자동으로 생성합니다.

### 주요 특징

- **완전 자동화**: 단일 스크립트로 전체 인프라 배포
- **멱등성**: 이미 존재하는 리소스는 재사용
- **에러 핸들링**: 각 단계별 예외 처리
- **로깅**: 상세한 배포 진행 상황 출력

---

## 사전 요구 사항

- AWS 자격 증명이 구성된 환경(`aws configure` 또는 환경 변수)
- Python 3.x 및 `boto3` 사용 가능
- 배포 리전에서 Bedrock, OpenSearch Serverless, EC2 등 필요 서비스 사용 가능

---

## 설정값

`installer.py` 상단에서 프로젝트 식별자와 리전을 바꿉니다(최소 3글자 이상 권장).

```python
# 기본값 (스크립트 내 실제 기본)
project_name = "strands-mcp"   # 프로젝트 이름 (최소 3자)
region = "us-west-2"         # AWS 리전
git_name = "strands-mcp"     # EC2 User Data 등에서 참조하는 저장소 이름

# 자동 생성되는 변수
account_id = sts_client.get_caller_identity()["Account"]
bucket_name = f"storage-for-{project_name}-{account_id}-{region}"
vector_index_name = project_name

# 커스텀 헤더 (CloudFront–ALB 통신용)
custom_header_name = "X-Custom-Header"
custom_header_value = f"{project_name}_12dab15e4s31"
```

---

## 생성되는 리소스

### 1. S3 버킷

- **이름**: `storage-for-{project_name}-{account_id}-{region}`
- **설정**:
  - CORS 활성화 (GET, POST, PUT)
  - 퍼블릭 액세스 차단
  - `docs/` 프리픽스(폴더) 생성

### 2. IAM 역할

`main()` 기준으로 다음 역할이 생성됩니다.

| 역할 이름 패턴 | 설명 |
|----------------|------|
| `role-knowledge-base-for-{project_name}-{region}` | Bedrock Knowledge Base |
| `role-agent-for-{project_name}-{region}` | Bedrock Agent |
| `role-ec2-for-{project_name}-{region}` | EC2 인스턴스 |
| `role-agentcore-memory-for-{project_name}-{region}` | AgentCore Memory |

> **참고**: `role-lambda-rag-for-{project_name}-{region}` 생성 함수는 스크립트에 정의되어 있으나, 현재 기본 배포 경로(`main()`)에서는 호출되지 않습니다.

### 3. Secrets Manager

- `tavilyapikey-{project_name}`: Tavily API 키(신규 생성 시 터미널에서 입력 요청, Enter로 빈 값 가능)

### 4. OpenSearch Serverless

- **컬렉션**: Vector 검색용 서버리스 컬렉션
- **정책**: 암호화, 네트워크, 데이터 액세스 정책
- **인덱스**: KNN 벡터 검색 인덱스 (1024차원, Titan Embed v2와 정합)

### 5. VPC 네트워킹

```
VPC (10.20.0.0/16)
├── Public Subnets (2개 AZ)
│   ├── Internet Gateway 연결
│   └── NAT Gateway 호스팅
├── Private Subnets (2개 AZ)
│   └── NAT Gateway를 통한 아웃바운드
├── Security Groups
│   ├── ALB SG (포트 80)
│   └── EC2 SG (8501, 443 등)
└── VPC Endpoints
    └── Bedrock Runtime 엔드포인트
```

### 6. Application Load Balancer

- **타입**: Internet-facing Application Load Balancer
- **리스너**: HTTP 포트 80
- **타겟 그룹**: EC2 인스턴스 (포트 8501) — 인스턴스 생성 후 별도 단계에서 등록

### 7. CloudFront 배포

- **오리진**:
  - 기본: ALB (동적 컨텐츠)
  - `/images/*`, `/docs/*`: S3 (정적 컨텐츠, OAI 사용)
- **캐시 정책**: Managed-CachingDisabled(동적 오리진)
- **프로토콜**: HTTP → HTTPS 리다이렉트

### 8. EC2 인스턴스

- **타입**: t3.medium
- **AMI**: Amazon Linux 2023 ECS 최적화 AMI 우선, 없으면 일반 AL2023 AMI로 폴백
- **볼륨**: 80GB gp3 (암호화)
- **배포 위치**: Private Subnet
- **이름 태그**: `app-for-{project_name}`

### 9. Bedrock Knowledge Base

- **스토리지**: OpenSearch Serverless
- **임베딩 모델**: Amazon Titan Embed Text v2 (1024차원)
- **파싱/청킹**: 스크립트 내 Bedrock Knowledge Base 설정에 따름

---

## 주요 함수

### 인프라 생성 함수

#### `create_s3_bucket()`

S3 버킷 생성 및 CORS, 퍼블릭 액세스 차단, `docs/` 객체 생성

#### `create_knowledge_base_role()` / `create_agent_role()` / `create_ec2_role()` / `create_agentcore_memory_role()`

각 IAM 역할 생성 및 인라인·관리형 정책 연결

#### `create_secrets()`

Secrets Manager에 Tavily 시크릿 생성(기존 시크릿이 있으면 재사용)

#### `create_opensearch_collection(ec2_role_arn, knowledge_base_role_arn)`

OpenSearch Serverless 컬렉션 및 보안 정책 생성

#### `create_knowledge_base_with_opensearch(opensearch_info, knowledge_base_role_arn, s3_bucket_name)`

벡터 인덱스 및 Knowledge Base, S3 데이터 소스 연결

#### `create_vpc()`

VPC, 서브넷, IGW/NAT, 보안 그룹, VPC 엔드포인트

#### `create_alb(vpc_info)`

Application Load Balancer 생성

#### `create_cloudfront_distribution(alb_info, s3_bucket_name)`

CloudFront 배포(ALB + S3 하이브리드), OAI 및 S3 버킷 정책

#### `create_ec2_instance(vpc_info, ec2_role_arn, knowledge_base_role_arn, opensearch_info, s3_bucket_name, cloudfront_domain, agentcore_memory_role_arn, knowledge_base_id)`

EC2 인스턴스 및 User Data(앱 배포 스크립트)

#### `create_alb_target_group_and_listener(alb_info, instance_id, vpc_info)`

타겟 그룹·리스너 생성 및 EC2 등록

#### `check_application_ready(domain)`

CloudFront URL 기준 애플리케이션 헬스 대기

### 헬퍼 함수

| 함수 | 설명 |
|------|------|
| `attach_inline_policy()` | IAM 역할에 인라인 정책 연결 |
| `create_security_group()` | 보안 그룹 생성 |
| `create_vpc_endpoint()` | VPC 엔드포인트 생성 |
| `classify_subnets()` | 서브넷을 퍼블릭/프라이빗으로 분류 |
| `create_vector_index_in_opensearch()` | OpenSearch에 벡터 인덱스 생성 |
| `check_application_ready()` | 애플리케이션 준비 상태 확인 |

---

## 실행 방법

### 기본 실행 (전체 인프라 배포)

```bash
python installer.py
```

3단계( Secrets )에서 Tavily 시크릿이 없을 때 **Tavily API 키 입력**을 요청합니다.

### 기존 EC2 인스턴스에 설정 스크립트 실행 (SSM)

```bash
# 인스턴스 이름으로 자동 탐색
python installer.py --run-setup

# 특정 인스턴스 ID 지정
python installer.py --run-setup i-1234567890abcdef0
```

### EC2 서브넷 배포 검증

```bash
python installer.py --verify-deployment
```

---

## 배포 순서

`main()`에서 실제로 수행되는 순서는 다음과 같습니다. 로그의 `[n/10]` 표기는 함수마다 부분적으로 겹칠 수 있으나, **논리적 순서**는 아래와 같습니다.

```
[1] S3 버킷 생성
       ↓
[2] IAM 역할 생성
       • Knowledge Base / Agent / EC2 / AgentCore Memory
       ↓
[3] Secrets Manager (Tavily)
       ↓
[4] OpenSearch Serverless 컬렉션 및 정책
       ↓
[4.5] Bedrock Knowledge Base (OpenSearch 연동, 벡터 인덱스)
       ↓
[5] VPC 및 네트워킹
       ↓
[6] Application Load Balancer
       ↓
[7] CloudFront (ALB + S3, OAI)
       ↓
[8] EC2 인스턴스 (User Data로 앱 설치)
       ↓
[9] ALB 타겟 그룹·리스너 및 EC2 등록
       ↓
[10] 애플리케이션 준비 상태 확인 (CloudFront 도메인)
       ↓
완료 — application/config.json 업데이트
```

---

## 배포 완료 후

배포가 완료되면 로그에 요약이 출력됩니다. 예시는 다음과 같습니다(값은 계정·실행 시점에 따라 다름).

```
================================================================
Infrastructure Deployment Completed Successfully!
================================================================
Summary:
  S3 Bucket: storage-for-strands-mcp-{account_id}-us-west-2
  VPC ID: vpc-xxxxxxxxx
  Public Subnets: subnet-xxx, subnet-yyy
  Private Subnets: subnet-aaa, subnet-bbb
  ALB DNS: http://alb-for-strands-mcp-xxxxxx.us-west-2.elb.amazonaws.com/
  CloudFront Domain: https://xxxxxxxxx.cloudfront.net
  EC2 Instance ID: i-xxxxxxxxx (deployed in private subnet)
  OpenSearch Endpoint: https://xxxxxxxx.us-west-2.aoss.amazonaws.com
  Knowledge Base ID: XXXXXXXXXX
  Knowledge Base Role: arn:aws:iam::...
  AgentCore Memory Role: arn:aws:iam::...

Total deployment time: XX.XX minutes
================================================================
```

### `application/config.json` 자동 갱신

배포 성공 시 다음 필드가 병합·저장됩니다.

- `projectName`, `accountId`, `region`
- `knowledge_base_id`, `knowledge_base_role`
- `collectionArn`, `opensearch_url`
- `s3_bucket`, `s3_arn`
- `sharing_url` (CloudFront HTTPS URL)
- `agentcore_memory_role`

### Docker 이미지 (저장소 루트 `Dockerfile`)

EC2 User Data에서 빌드·실행하는 컨테이너는 저장소의 `Dockerfile`과 일치합니다. 주요 내용은 다음과 같습니다.

```dockerfile
FROM --platform=linux/amd64 python:3.13-slim

WORKDIR /app

# Node.js (npx 등 MCP 서버용)
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN pip install streamlit==1.41.0 streamlit-chat pandas numpy boto3
RUN pip install langchain_aws langchain langchain_community langchain_experimental langchain-text-splitters
RUN pip install mcp
RUN pip install aioboto3 opensearch-py
RUN pip install tavily-python==0.5.0 rizaio==0.8.0 pytz==2024.2 beautifulsoup4==4.12.3
RUN pip install plotly_express==0.4.1 matplotlib==3.10.0 chembl-webresource-client pytrials
RUN pip install PyPDF2==3.0.1 wikipedia requests uv kaleido diagrams reportlab arxiv graphviz sarif-om==1.0.4
RUN pip install rich==13.9.0 bedrock-agentcore pyyaml
RUN pip install strands-agents strands-agents-tools reportlab arize-phoenix colorama finance-datareader

RUN mkdir -p /root/.streamlit
COPY config.toml /root/.streamlit/

COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["python", "-m", "streamlit", "run", "application/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### 주의사항

- CloudFront 배포가 전 구간에서 안정화되기까지 **15~20분** 걸릴 수 있습니다.
- EC2 User Data가 Docker 이미지 빌드·실행을 수행하므로, 인스턴스 기동 직후에는 응답이 늦을 수 있습니다.
- `installer.py`의 `project_name` / `region` / `git_name`을 바꾼 뒤에는 버킷 이름·역할 이름·도메인이 모두 해당 값을 따릅니다.

---

## 에러 처리

| 상황 | 처리 방법 |
|------|----------|
| 리소스 이미 존재 | 가능한 경우 기존 리소스 재사용 |
| S3 버킷 이름 충돌 | 다른 계정/리전이 아니면 `BucketAlreadyOwnedByYou` 등으로 재사용 |
| 시크릿 이미 존재 | 기존 ARN 사용, 새 키 입력 없이 진행 |
| 배포 실패 | 로그에 예외 및 스택 트레이스 출력 |

배포 실패 시 `Deployment Failed!` 블록과 함께 원인 메시지를 확인하세요.
