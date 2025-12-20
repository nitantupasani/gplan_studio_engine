#include "bfs.h"

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

int count_corridor_components(int* layout, int* region, int height, int width, int corridor_final) {
    char* visited = (char*)calloc(height * width, sizeof(char));
    if (!visited) return 0;
    int num_components = 0;
    int dr[] = {0, 0, 1, -1};
    int dc[] = {1, -1, 0, 0};
    Queue* q = create_queue(height * width); 
    for (int r = 0; r < height; r++) {
        for (int c = 0; c < width; c++) {
            int idx = r * width + c;
            if (layout[idx] == corridor_final && !visited[idx]) {
                num_components++;
                // BFS
                Point start = {r, c};
                enqueue(q, start);
                visited[idx] = 1;

                while (!is_empty(q)) {
                    Point current = dequeue(q);
                    for (int d = 0; d < 4; d++) {
                        int nr = current.r + dr[d];
                        int nc = current.c + dc[d];
                        if (nr >= 0 && nr < height && nc >= 0 && nc < width) {
                            int nidx = nr * width + nc;
                            if (region[nidx] != (int)'#' && layout[nidx] == corridor_final && !visited[nidx]) {
                                visited[nidx] = 1;
                                Point neighbor = {nr, nc};
                                enqueue(q, neighbor);
                            }
                        }
                    }
                }
            }
        }
    }

    destroy_queue(q);
    free(visited);
    return num_components;
}

int has_unusable_neighbor(int* matrix, int rows, int cols, int r, int c, int unusable) {
    int dr[] = {0, 0, 1, -1};
    int dc[] = {1, -1, 0, 0};
    for (int d = 0; d < 4; d++) {
        int nr = r + dr[d];
        int nc = c + dc[d];
        if (nr >= 0 && nr < rows && nc >= 0 && nc < cols) {
            if (matrix[nr * cols + nc] == unusable) {
                return 1;
            }
        }
    }
    return 0;
}

int has_room_neighbor(int* matrix, int rows, int cols, int r, int c, int corridor_final) {
    int dr[] = {0, 0, 1, -1};
    int dc[] = {1, -1, 0, 0};
    for (int d = 0; d < 4; d++) {
        int nr = r + dr[d];
        int nc = c + dc[d];
        if (nr >= 0 && nr < rows && nc >= 0 && nc < cols) {
            int val = matrix[nr * cols + nc];
            if (val > 0 && val != corridor_final) {
                return 1;
            }
        }
    }
    return 0;
}

void corridor_creator(int* matrix, int height, int width, int corridor_width, int corridor_final, int unusable) {
    int rows = height;
    int cols = width;
    int EMPTY = 0;
    
    // Horizontal scan: fill gaps between rooms in same row
    for (int r = 0; r < rows; r++) {
        int c = 0;
        while (c < cols) {
            // Find start of potential gap (first room cell)
            if (matrix[r * cols + c] > 0) {
                int left_room = matrix[r * cols + c];
                // Skip over this room
                while (c < cols && matrix[r * cols + c] == left_room) {
                    c++;
                }
                // Now c points to first non-left_room cell
                // Scan for empty cells followed by a different room
                int gap_start = c;
                while (c < cols && matrix[r * cols + c] == EMPTY) {
                    c++;
                }
                int gap_end = c;
                int gap_len = gap_end - gap_start;
                
                // Check if we found a different room at the end
                if (c < cols && matrix[r * cols + c] > 0 && matrix[r * cols + c] != left_room) {
                    // Gap is between two different rooms
                    if (gap_len >= 2) {
                        int all_valid = 1;
                        for (int cc = gap_start; cc < gap_end; cc++) {
                            if (has_unusable_neighbor(matrix, rows, cols, r, cc, unusable)) {
                                all_valid = 0;
                                break;
                            }
                        }
                        
                        if (all_valid) {
                            for (int cc = gap_start; cc < gap_end; cc++) {
                                matrix[r * cols + cc] = corridor_final;
                            }
                        }
                    }
                }
            } else {
                c++;
            }
        }
    }
    
    // Vertical scan: fill gaps between rooms in same column
    for (int c = 0; c < cols; c++) {
        int r = 0;
        while (r < rows) {
            // Find start of potential gap (first room cell)
            if (matrix[r * cols + c] > 0) {
                int top_room = matrix[r * cols + c];
                // Skip over this room
                while (r < rows && matrix[r * cols + c] == top_room) {
                    r++;
                }
                // Now r points to first non-top_room cell
                // Scan for empty cells followed by a different room
                int gap_start = r;
                while (r < rows && matrix[r * cols + c] == EMPTY) {
                    r++;
                }
                int gap_end = r;
                int gap_len = gap_end - gap_start;
                
                // Check if we found a different room at the end
                if (r < rows && matrix[r * cols + c] > 0 && matrix[r * cols + c] != top_room) {
                    // Gap is between two different rooms
                    if (gap_len >= 2 && gap_len <= corridor_width) {
                        int all_valid = 1;
                        for (int rr = gap_start; rr < gap_end; rr++) {
                            if (has_unusable_neighbor(matrix, rows, cols, rr, c, unusable)) {
                                all_valid = 0;
                                break;
                            }
                        }
                        
                        if (all_valid) {
                            for (int rr = gap_start; rr < gap_end; rr++) {
                                matrix[rr * cols + c] = corridor_final;
                            }
                        }
                    }
                }
            } else {
                r++;
            }
        }
    }
    
    // Conditional boundary clearing: only clear edge corridors with no room neighbors
    // Top row
    for (int c = 0; c < cols; c++) {
        if (matrix[0 * cols + c] == corridor_final && !has_room_neighbor(matrix, rows, cols, 0, c, corridor_final)) {
            matrix[0 * cols + c] = EMPTY;
        }
    }
    
    // Bottom row
    for (int c = 0; c < cols; c++) {
        if (matrix[(rows-1) * cols + c] == corridor_final && !has_room_neighbor(matrix, rows, cols, rows-1, c, corridor_final)) {
            matrix[(rows-1) * cols + c] = EMPTY;
        }
    }
    
    // Left column
    for (int r = 0; r < rows; r++) {
        if (matrix[r * cols + 0] == corridor_final && !has_room_neighbor(matrix, rows, cols, r, 0, corridor_final)) {
            matrix[r * cols + 0] = EMPTY;
        }
    }
    
    // Right column
    for (int r = 0; r < rows; r++) {
        if (matrix[r * cols + (cols-1)] == corridor_final && !has_room_neighbor(matrix, rows, cols, r, cols-1, corridor_final)) {
            matrix[r * cols + (cols-1)] = EMPTY;
        }
    }
}