# 네이버 관제 추가 속도 개선 코드 교체 — 2026-10-08

현재운영6198be3에서 제품e4f64e165ebdf81d4127218d5c91ff6904e75958로 교체할 준비다. 변경한 운영파일은 catalog_links.py, dashboard.py, inventory.py 세개뿐이다. 소스봉인은Linux3.12 encoder의716d849b68d72cb03489bc16da1cee3d9a0f31cb16612287b407fe244dea84c6으로 고정한다. 이전봉인b9071a746aa1879d518849bb5a76a8d2259a5d77853e28298fcd26fc7ea0d90e와 store.py의 양쪽 동일SHA5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94를 검사한다.

code-only controller는DB를열지않고현재파일을유지한다. schema11, compose/소켓/서비스/nginx/권한/API/legacy 경로는 그대로다. 허용파일이나테스트폴더승인이넓어지면작업전거절한다. 실제두archive에서 compatible_source 검사를통과했다.

Mac preview합성330개 실패0 skip3, Linux관련188개 실패0 skip3. Linux전체의Docker CLI템플릿검사1개는격리컨테이너에Docker CLI가없어실패했다. 새변경대상검사는통과했고추가설치를하지않았다. 제품회귀는별도Linux83개,236개,36개 묶음이통과했다(중복합산하지않음).

이문서는배포준비기록이다. 실제운영교체결과와인증브라우저속도는교체뒤별도확인한다. 기존계정·계약·운영데이터변경권한을확장하지않는다.
