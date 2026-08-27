# 규격 검색 환경

여기에서는 규격 검색 환경 구성을 위한 RAG를 구현하는 방법에 대해 설명합니다.

## Knowledge Base

완전 관리형 RAG서비스인 Knowledge Base는 자료의 추가 삭제가 용이하고 안정적 성능을 제공합니다. 여기서는 Knowledge Base + OpenSearch 행태로 규격을 검색하는 환경을 제공합니다.

## 파일 준비

"NFPA855_2023.pdf"의 크기는 129MB (125 page)입니다. Knowledge Base에서는 50MB 이하로 파일을 관리하도록 요청하고 있습니다. 따라서 "NFPA855_2023_1.pdf", "NFPA855_2023_2.pdf", "NFPA855_2023_3.pdf"와 같이 파일을 준비합니다. 파일명이 다른 경우에 이어지는 항목이 잘릴수 있습니다. 따라서, 페이지를 나눌때에 1-40, 40-80, 80-125와 같이 한 페이지가 겹치도록 분리합니다. 

채팅창의 +버튼을 선택하여 Upload to RAG를 선택합니다.

<img width="917" height="319" alt="image" src="https://github.com/user-attachments/assets/096ddeca-0216-4583-a4c1-ebb7b4902fed" />

아래와 같이 파일 3개를 선택합니다. 

<img width="244" height="87" alt="image" src="https://github.com/user-attachments/assets/66f11d32-a6f6-44b7-bb32-65d0b80bfd6c" />

업로드가 완료되면 자동으로 sync 동작을 수행합니다. Amazon S3에 접속해보면 아래와 같이 파일 3개와 함께 json 파일이 생성되어 있음을 알수 있습니다.

<img width="1088" height="505" alt="image" src="https://github.com/user-attachments/assets/114d7740-b80f-42f1-b2ea-fe229a41f097" />

파일명.metadata.json에는 아래와 같은 정보가 있어서, 파일의 소유자, team, 생성일, 보안여부를 알수 있습니다.

```java
{
  "metadataAttributes": {
    "owner": {
      "value": {
        "type": "STRING_LIST",
        "stringListValue": [
          "ksdyb"
        ]
      },
      "includeForEmbedding": false
    },
    "team": {
      "value": {
        "type": "STRING",
        "stringValue": "mycompany"
      },
      "includeForEmbedding": false
    },
    "created_time": {
      "value": {
        "type": "NUMBER",
        "numberValue": 1787810389
      },
      "includeForEmbedding": false
    },
    "is_confidential": {
      "value": {
        "type": "BOOLEAN",
        "booleanValue": false
      },
      "includeForEmbedding": false
    }
  }
}
```

