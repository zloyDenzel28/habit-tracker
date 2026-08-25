FROM node:20-alpine

ENV TZ=UTC
WORKDIR /app

# npm ci вместо npm install: ставит ровно то, что записано в lock-файле.
# Без него каждая пересборка заново разрешает диапазоны версий и может
# притащить другие пакеты — а установка здесь и без того долгая.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
