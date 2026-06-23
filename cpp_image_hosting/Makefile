CXX := g++
CXXFLAGS := -std=c++20 -Wall -Wextra -O2

TARGET := image_hosting
SRC := src/main.cpp

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<

run: $(TARGET)
	./$(TARGET) 19090

clean:
	rm -f $(TARGET)
