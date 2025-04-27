go_dockerfile = """FROM golang:1.18-alpine AS build

WORKDIR /app

COPY go.* ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o /app/server

FROM alpine:3.15
WORKDIR /app
COPY --from=build /app/server .
COPY .env .env

EXPOSE 8080

CMD ["./server"]
"""