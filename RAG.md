# 규격 검색 환경

여기에서는 규격 검색 환경 구성을 위한 RAG를 구현하는 방법에 대해 설명합니다.

## Knowledge Base

완전 관리형 RAG서비스인 Knowledge Base는 자료의 추가 삭제가 용이하고 안정적 성능을 제공합니다. 여기서는 Knowledge Base + OpenSearch 행태로 규격을 검색하는 환경을 제공합니다.

## 파일 준비

"NFPA855_2023.pdf"의 크기는 129MB (125 page)입니다. Knowledge Base에서는 50MB 이하로 파일을 관리하도록 요청하고 있습니다. 따라서 "NFPA855_2023_1.pdf", "NFPA855_2023_2.pdf", "NFPA855_2023_3.pdf"와 같이 파일을 준비합니다. 

