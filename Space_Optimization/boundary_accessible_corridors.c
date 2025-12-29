#include "boundary_accessible_corridors.h"
#include <stdlib.h>
#include <string.h>

typedef struct {
    int r, c;
} Point;

typedef struct {
    Point* data;
    int front, rear, size, capacity;
} Queue;

Queue* create_queue(int capacity) {
    Queue* q = (Queue*)malloc(sizeof(Queue));
    q->data = (Point*)malloc(sizeof(Point) * capacity);
    q->front = 0;
    q->rear = 0;
    q->size = 0;
    q->capacity = capacity;
    return q;
}

void destroy_queue(Queue* q) {
    free(q->data);
    free(q);
}

int is_empty(Queue* q) {
    return q->size == 0;
}

void enqueue(Queue* q, Point p) {
    if (q->size == q->capacity) {
        return;
    }
    q->data[q->rear] = p;
    q->rear = (q->rear + 1) % q->capacity;
    q->size++;
}

Point dequeue(Queue* q) {
    Point p = q->data[q->front];
    q->front = (q->front + 1) % q->capacity;
    q->size--;
    return p;
}

int count_boundary_accessible_corridors(int* layout, int* region, int height, int width, int corridor_final) {
    int entry_points = 0;
    int dr[] = {0, 0, 1, -1};
    int dc[] = {1, -1, 0, 0};

    // Count corridor cells directly on the boundary
    for (int r = 0; r < height; r++) {
        for (int c = 0; c < width; c++) {
            int idx = r * width + c;
            if (layout[idx] == corridor_final && region[idx] != (int)'#') {
                int is_boundary = r == 0 || r == height - 1 || c == 0 || c == width - 1;
                if (is_boundary) {
                    entry_points++;
                }
            }
        }
    }

    // Find boundary-accessible empty cells
    Point* boundary_empty = NULL;
    int boundary_empty_count = 0;
    int boundary_empty_capacity = 1000;

    boundary_empty = (Point*)malloc(sizeof(Point) * boundary_empty_capacity);

    for (int r = 0; r < height; r++) {
        for (int c = 0; c < width; c++) {
            int idx = r * width + c;
            if (region[idx] != (int)'#' && layout[idx] == 0) {  // Empty and usable
                int is_boundary = r == 0 || r == height - 1 || c == 0 || c == width - 1;
                int is_adjacent_to_unusable = 0;

                for (int d = 0; d < 4; d++) {
                    int nr = r + dr[d];
                    int nc = c + dc[d];
                    if (nr >= 0 && nr < height && nc >= 0 && nc < width &&
                        region[nr * width + nc] == (int)'#') {
                        is_adjacent_to_unusable = 1;
                        break;
                    }
                }

                if (is_boundary || is_adjacent_to_unusable) {
                    if (boundary_empty_count >= boundary_empty_capacity) {
                        boundary_empty_capacity *= 2;
                        boundary_empty = (Point*)realloc(boundary_empty, sizeof(Point) * boundary_empty_capacity);
                    }
                    boundary_empty[boundary_empty_count].r = r;
                    boundary_empty[boundary_empty_count].c = c;
                    boundary_empty_count++;
                }
            }
        }
    }

    if (boundary_empty_count > 0) {
        char* visited = (char*)calloc(height * width, sizeof(char));
        Queue* q = create_queue(height * width);

        // Mark all boundary empty cells as visited and accessible
        for (int i = 0; i < boundary_empty_count; i++) {
            int r = boundary_empty[i].r;
            int c = boundary_empty[i].c;
            int idx = r * width + c;
            visited[idx] = 1;
            enqueue(q, boundary_empty[i]);
        }

        // BFS to find all connected empty cells
        while (!is_empty(q)) {
            Point current = dequeue(q);
            for (int d = 0; d < 4; d++) {
                int nr = current.r + dr[d];
                int nc = current.c + dc[d];
                if (nr >= 0 && nr < height && nc >= 0 && nc < width) {
                    int nidx = nr * width + nc;
                    if (!visited[nidx] && region[nidx] != (int)'#' && layout[nidx] == 0) {
                        visited[nidx] = 1;
                        Point neighbor = {nr, nc};
                        enqueue(q, neighbor);
                    }
                }
            }
        }

        // Count empty cells adjacent to corridors
        for (int r = 0; r < height; r++) {
            for (int c = 0; c < width; c++) {
                int idx = r * width + c;
                if (visited[idx]) {
                    int has_corridor_neighbor = 0;
                    for (int d = 0; d < 4; d++) {
                        int nr = r + dr[d];
                        int nc = c + dc[d];
                        if (nr >= 0 && nr < height && nc >= 0 && nc < width) {
                            int nidx = nr * width + nc;
                            if (layout[nidx] == corridor_final && region[nidx] != (int)'#') {
                                has_corridor_neighbor = 1;
                                break;
                            }
                        }
                    }

                    if (has_corridor_neighbor) {
                        entry_points++;
                    }
                }
            }
        }

        destroy_queue(q);
        free(visited);
    }

    free(boundary_empty);
    return entry_points;
}