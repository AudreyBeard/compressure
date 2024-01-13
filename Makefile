DPATH_INPUT := "${HOME}/compressure-input"
DPATH_OUTPUT := "${HOME}/compressure-output"
FPATH_COMPRESSURE_COMMAND := "sample_compressure_command.sh"

build: Dockerfile
	docker build -t compressure .

run: build
	mkdir -p $(DPATH_INPUT)
	mkdir -p $(DPATH_OUTPUT)
	docker run -it \
	    -v $(DPATH_INPUT):/input \
		-v $(DPATH_OUTPUT):/output \
		compressure \
		$(FPATH_COMPRESSURE_COMMAND)
