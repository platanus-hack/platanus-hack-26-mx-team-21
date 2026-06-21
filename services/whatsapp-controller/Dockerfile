# Kapso WhatsApp controller — runs via tsx (TypeScript executed directly, no build step).
FROM node:20-slim

WORKDIR /app

# Install deps first for layer caching. tsx is a devDependency, so install everything.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src

ENV PORT=8080
EXPOSE 8080

# npm start -> tsx src/index.ts
CMD ["npm", "start"]
