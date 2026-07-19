# API

Aplicação FastAPI mínima com contrato OpenAPI e health checks separados:

- `/api/v1/health/live`: processo HTTP ativo;
- `/api/v1/health/ready`: API e PostgreSQL prontos;
- `/api/v1/docs`: Swagger UI;
- `/api/v1/openapi.json`: contrato OpenAPI.
