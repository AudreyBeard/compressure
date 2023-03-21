FPATH_COMPRESSURE_COMMAND := "sample_compressure_command.sh"
DPATH_INPUT := "/media/USB_2TB"
DPATH_OUTPUT := "${HOME}/data/video/output"

build: Dockerfile
	docker build -t compressure .

run: build
	docker run -it \
	    -v $(DPATH_INPUT):/input \
		-v $(DPATH_OUTPUT):/output \
		compressure \
		$(FPATH_COMPRESSURE_COMMAND)
