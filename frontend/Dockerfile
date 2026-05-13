# Multi-stage: build con Node, sirve con nginx
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY index.html ./
COPY public ./public
COPY src ./src

# El backend está en otro container; configurar VITE_API_BASE en build time
ARG VITE_API_BASE=http://localhost:8010
ENV VITE_API_BASE=$VITE_API_BASE

RUN npm run build


FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
