# API 키 설정

이 프로그램은 실행 중인 컴퓨터의 `DART_API_KEY` 환경변수를 읽습니다. PC 설정은 클라우드와 별개입니다. 이미 Python과 VS Code를 설치했다면 다시 설치할 필요는 없습니다. Python 버전만 3.11 이상인지 확인하세요.

PC의 PowerShell에서 아래를 실행합니다. 입력할 때 키가 가려지며 키 값은 명령 기록에 직접 적지 않습니다.

```powershell
$dartKeyInput = Read-Host 'OpenDART API 키 입력' -AsSecureString
$env:DART_API_KEY = [System.Net.NetworkCredential]::new('', $dartKeyInput).Password
[Environment]::SetEnvironmentVariable('DART_API_KEY', $env:DART_API_KEY, 'User')
Remove-Variable dartKeyInput
```

VS Code를 완전히 종료한 다음 다시 여세요. 다음 명령은 값 대신 존재 여부만 출력합니다.

```powershell
.\.venv\Scripts\python.exe -c "import os; print('설정됨' if os.environ.get('DART_API_KEY') else '미설정')"
```

클라우드에서 Codex가 실제 5종목 시험을 하려면 환경 설정의 비밀정보 항목에 `DART_API_KEY` 값을 입력해야 합니다. 값은 채팅에 보내지 않습니다. 이 키의 HTTPS 사용 목적지는 `opendart.fss.or.kr`입니다. 클라우드에서 쓰기 원치 않으면 완성한 프로그램을 PC에서 실행하고 키를 제외한 로그·결과로 검토할 수 있습니다.

변수의 존재는 키의 유효성·허용 IP·이용한도를 보장하지 않습니다. 실제 API 응답으로 확인해야 합니다. 프로그램은 키가 포함된 요청 URL이나 서버의 원문 오류 메시지를 로그에 기록하지 않습니다.

이 문서의 PowerShell 명령과 `.bat` 실행은 아직 Windows에서 시험하지 않았습니다. 클라우드는 Linux입니다.
