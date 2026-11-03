# The image content comes from the branch that builds it.
FROM alpine:3.21
ARG CONTENT=unset
RUN echo "slow" && sleep 20
RUN echo "$CONTENT" > /owner.txt
