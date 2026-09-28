# Composição runtime Pluggy atrás de flags fail-closed

Status: **issue #82**.

A API instala o executor, mas mantém `APP_BANKING_ENABLED=false` e `APP_BANKING_PLUGGY_ENABLED=false` por padrão. O provider fica administrativamente disponível somente com a flag Pluggy; a ativação exige também a flag global. O executor só é construído com ambas as flags, sem ler credenciais, criar transporte ou executar rede no startup. O `BankingProviderRegistry` continua vazio e congelado, e nenhum endpoint foi criado neste recorte.
