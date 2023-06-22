FROM --platform=linux/amd64 node:10-alpine

RUN npm cache clean --force && \
	npm config set strict-ssl false && \
	apk add wget unzip

WORKDIR /gremlin-visualizer-master

COPY . .

RUN npm install

EXPOSE 3000 3001

CMD npm start
