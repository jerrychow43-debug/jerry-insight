CXX := g++
CXXFLAGS := -std=c++20 -Wall -Wextra -O2 -pthread

SERVER := rpc_server
CLIENT := rpc_client
SERVER_SRC := src/server.cpp
CLIENT_SRC := src/client.cpp

.PHONY: all clean run-server

all: $(SERVER) $(CLIENT)

$(SERVER): $(SERVER_SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<

$(CLIENT): $(CLIENT_SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<

run-server: $(SERVER)
	./$(SERVER) 18888

clean:
	rm -f $(SERVER) $(CLIENT)
