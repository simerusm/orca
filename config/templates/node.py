node_dockerfile = """FROM node:16-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Use environment variables
COPY .env .env
ENV $(cat .env | xargs)

RUN npm run build || echo "No build script found"

EXPOSE 3000

CMD ["npm", "start"]
"""